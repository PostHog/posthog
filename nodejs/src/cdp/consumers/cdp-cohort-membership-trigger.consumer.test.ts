import '../../../tests/helpers/mocks/consumer.mock'
import { createMockJobQueue } from '../../../tests/helpers/mocks/job-queue.mock'
import '../../../tests/helpers/mocks/producer.mock'

import { HogFlow } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { createTestTeamFixture } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_FLOW_MASK_EXAMPLES } from '../_tests/examples'
import { createCohortMembershipEvent, createKafkaMessage } from '../_tests/fixtures'
import { insertHogFlow } from '../_tests/fixtures-hogflows'
import { COHORT_MEMBERSHIP_CHANGED_EVENT } from '../services/cohorts/cohort-membership-repository'
import { CyclotronJobInvocationHogFlow } from '../types'
import { CdpCohortMembershipTriggerConsumer } from './cdp-cohort-membership-trigger.consumer'

describe('CdpCohortMembershipTriggerConsumer', () => {
    let processor: CdpCohortMembershipTriggerConsumer
    let hub: Hub
    let team: Team
    let mockQueueInvocations: jest.MockedFunction<any>

    const cohortFlow = (cohortId: number, transition: 'entered' | 'left'): HogFlow =>
        new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withSimpleWorkflow({ trigger: { type: 'cohort', cohort_id: cohortId, transition } })
            .build()

    beforeEach(async () => {
        hub = await createHub({ SITE_URL: 'http://localhost:8000' })
        team = (await createTestTeamFixture(hub.postgres)).team
        jest.spyOn(hub.quotaLimiting, 'isTeamQuotaLimited').mockResolvedValue(false)

        const mockJobQueue = createMockJobQueue()
        processor = new CdpCohortMembershipTriggerConsumer(hub, createCdpConsumerDeps(hub), {
            hogflowQueue: mockJobQueue,
        })
        mockQueueInvocations = mockJobQueue.queueInvocations
        await processor.start()
    })

    afterEach(async () => {
        await processor.stop()
        await closeHub(hub)
    })

    it('starts a run only for workflows triggered by that cohort and transition', async () => {
        const matching = await insertHogFlow(hub.postgres, cohortFlow(42, 'entered'))
        await insertHogFlow(hub.postgres, cohortFlow(42, 'left'))
        await insertHogFlow(hub.postgres, cohortFlow(7, 'entered'))
        const change = createCohortMembershipEvent({
            team_id: team.id,
            cohort_id: 42,
            status: 'entered',
            last_updated: '2026-10-20 10:00:00.123456',
        })

        const globals = await processor._parseKafkaBatch([createKafkaMessage(change)])
        const { invocations, backgroundTask } = await processor.processBatch(globals)
        await backgroundTask

        expect(invocations).toHaveLength(1)
        const invocation = invocations[0] as CyclotronJobInvocationHogFlow
        expect(invocation.functionId).toBe(matching.id)
        expect(invocation.state.personId).toBe(change.person_id)
        expect(invocation.state.event.event).toBe(COHORT_MEMBERSHIP_CHANGED_EVENT)
        expect(invocation.state.event.properties).toEqual({
            cohort_id: 42,
            status: 'entered',
            $membership_version: '2026-10-20 10:00:00.123456',
        })
        expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)
    })

    it('starts one run per person when the workflow runs once per person', async () => {
        const flow = cohortFlow(42, 'entered')
        flow.trigger_masking = HOG_FLOW_MASK_EXAMPLES.onceEver.trigger_masking
        await insertHogFlow(hub.postgres, flow)
        const rejoiner = createCohortMembershipEvent({ team_id: team.id, cohort_id: 42, status: 'entered' })
        const other = createCohortMembershipEvent({ team_id: team.id, cohort_id: 42, status: 'entered' })

        const first = await processor.processBatch(await processor._parseKafkaBatch([createKafkaMessage(rejoiner)]))
        await first.backgroundTask
        const second = await processor.processBatch(
            await processor._parseKafkaBatch([createKafkaMessage(rejoiner), createKafkaMessage(other)])
        )
        await second.backgroundTask

        expect(
            first.invocations.map((invocation) => (invocation as CyclotronJobInvocationHogFlow).state.personId)
        ).toEqual([rejoiner.person_id])
        expect(
            second.invocations.map((invocation) => (invocation as CyclotronJobInvocationHogFlow).state.personId)
        ).toEqual([other.person_id])
    })

    it.each([true, false])(
        'on redelivery after a partly failed queue, starts only the runs that were not queued (parallel inserts: %s)',
        async (parallel) => {
            hub.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE = 1
            hub.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES = parallel
            const flow = cohortFlow(42, 'entered')
            flow.trigger_masking = HOG_FLOW_MASK_EXAMPLES.onceEver.trigger_masking
            await insertHogFlow(hub.postgres, flow)
            const queuedChange = createCohortMembershipEvent({ team_id: team.id, cohort_id: 42, status: 'entered' })
            const failedChange = createCohortMembershipEvent({ team_id: team.id, cohort_id: 42, status: 'entered' })
            const messages = [createKafkaMessage(queuedChange), createKafkaMessage(failedChange)]
            mockQueueInvocations.mockImplementation((batch: CyclotronJobInvocationHogFlow[]) =>
                batch[0].state.personId === failedChange.person_id
                    ? Promise.reject(new Error('queue unavailable'))
                    : Promise.resolve()
            )

            const failed = await processor.processBatch(await processor._parseKafkaBatch(messages))
            await expect(failed.backgroundTask).rejects.toThrow('queue unavailable')
            mockQueueInvocations.mockResolvedValue(undefined)
            const redelivered = await processor.processBatch(await processor._parseKafkaBatch(messages))
            await redelivered.backgroundTask

            expect(
                redelivered.invocations.map(
                    (invocation) => (invocation as CyclotronJobInvocationHogFlow).state.personId
                )
            ).toEqual([failedChange.person_id])
        }
    )

    it('fails the batch when loading workflows fails, so the change is retried', async () => {
        jest.spyOn(processor['hogFlowManager'], 'getHogFlowsForTeams').mockRejectedValue(
            new Error('canceling statement due to conflict with recovery')
        )
        const change = createCohortMembershipEvent({ team_id: team.id, cohort_id: 42, status: 'entered' })

        await expect(processor._parseKafkaBatch([createKafkaMessage(change)])).rejects.toThrow('conflict with recovery')
    })

    it("loads a team's workflows once per batch, however many changes the batch holds for it", async () => {
        await insertHogFlow(hub.postgres, cohortFlow(42, 'entered'))
        const lookup = jest.spyOn(processor['hogFlowManager'], 'getHogFlowsForTeams')
        const messages = [1, 2, 3].map(() =>
            createKafkaMessage(createCohortMembershipEvent({ team_id: team.id, cohort_id: 42, status: 'entered' }))
        )

        const globals = await processor._parseKafkaBatch(messages)

        expect(globals).toHaveLength(3)
        expect(lookup).toHaveBeenCalledTimes(1)
        expect(lookup).toHaveBeenCalledWith([team.id])
    })

    it.each(['seed', 'reconcile'])('starts no run for a %s message', async (origin) => {
        await insertHogFlow(hub.postgres, cohortFlow(42, 'entered'))
        const change = createCohortMembershipEvent({ team_id: team.id, cohort_id: 42, status: 'entered', origin })

        const globals = await processor._parseKafkaBatch([createKafkaMessage(change)])

        expect(globals).toHaveLength(0)
    })
})
