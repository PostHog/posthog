import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { InternalFetchService } from '~/common/services/internal-fetch'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { Team } from '~/types'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_FLOW_MASK_EXAMPLES } from '../_tests/examples'
import type { CyclotronV2DequeuedJob, CyclotronV2JobProducer, CyclotronV2Worker } from '../services/cyclotron-v2'
import { HogFlowBatchPersonQueryService } from '../services/hogflows/hogflow-batch-person-query.service'
import { CyclotronJobInvocationHogFlow } from '../types'
import {
    CdpCyclotronWorkerBatchResolve,
    buildAccountHogFlowInvocation,
} from './cdp-cyclotron-worker-batch-resolve.consumer'

jest.setTimeout(20000)

describe('buildAccountHogFlowInvocation', () => {
    const team = { id: 123, name: 'Test team' } as Team
    // A non-default version, so the flowVersion assertion can't pass by accident.
    const hogFlow: HogFlow = { ...new FixtureHogFlowBuilder().withTeamId(team.id).build(), version: 4 }

    it('carries the account group key and no person', () => {
        const invocation = buildAccountHogFlowInvocation({
            siteUrl: 'https://us.posthog.com',
            parentRunId: 'batch-job-1',
            team,
            hogFlow,
            externalId: 'acme-1',
            groupType: 'customer',
            defaultVariables: { greeting: 'hi' },
        })

        const state = invocation.state as CyclotronJobInvocationHogFlow['state']

        expect(state.event.event).toEqual('$batch_hog_flow_invocation')
        // distinct_id doubles as the per-account key for invocation_results; it must NOT
        // resolve to a person (the hogflow worker skips the lookup for account audiences).
        expect(state.event.distinct_id).toEqual('acme-1')
        expect(state.event.properties['$groups']).toEqual({ customer: 'acme-1' })
        expect(state.personId).toBeUndefined()
        // The stamp is what the hogflow worker trusts when the live trigger has been
        // edited to a person audience while these children were still queued.
        expect(state.accountAudience).toBe(true)
        // Account broadcasts convert long after the send, so the run has to carry the version
        // that sent or the conversion is credited to whatever is published by then.
        expect(state.flowVersion).toBe(4)
        expect(state.variables).toEqual({ greeting: 'hi' })
        expect(invocation.parentRunId).toEqual('batch-job-1')
        expect(invocation.queue).toEqual('hogflow')
        expect((invocation as any).person).toBeUndefined()
    })

    // HogMaskerService.filterByMasking() only recognizes an invocation as a hog flow
    // invocation (and applies trigger_masking) when it carries a `hogFlow` object — if this
    // regresses, trigger_masking silently stops applying to batch-triggered runs again.
    it('attaches the hogFlow so trigger_masking can be applied by the batch resolver', () => {
        const maskedHogFlow: HogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withTriggerMasking(HOG_FLOW_MASK_EXAMPLES.everyTime.trigger_masking)
            .build()

        const invocation = buildAccountHogFlowInvocation({
            siteUrl: 'https://us.posthog.com',
            parentRunId: 'batch-job-1',
            team,
            hogFlow: maskedHogFlow,
            externalId: 'acme-1',
            groupType: 'customer',
            defaultVariables: {},
        })

        expect(invocation.hogFlow).toBe(maskedHogFlow)
        expect(invocation.hogFlow.trigger_masking).toEqual(HOG_FLOW_MASK_EXAMPLES.everyTime.trigger_masking)
    })
})

describe('CdpCyclotronWorkerBatchResolve cancel', () => {
    let hub: Hub

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const buildFlaggedJob = (): jest.Mocked<CyclotronV2DequeuedJob> =>
        ({
            id: 'resolver-1',
            teamId: 7,
            functionId: 'flow-1',
            queueName: 'hogflow_batch_resolve',
            priority: 0,
            scheduled: DateTime.now(),
            created: DateTime.now(),
            parentRunId: 'batch-1',
            transitionCount: 1,
            state: null,
            distinctId: null,
            personId: null,
            actionId: null,
            cancelRequestedAt: DateTime.now(),
            ack: jest.fn().mockResolvedValue(undefined),
            fail: jest.fn().mockResolvedValue(undefined),
            reschedule: jest.fn().mockResolvedValue(undefined),
            cancel: jest.fn().mockResolvedValue(undefined),
            heartbeat: jest.fn().mockResolvedValue(undefined),
        }) as unknown as jest.Mocked<CyclotronV2DequeuedJob>

    const startAndDeliver = async (cancelJobs: jest.Mock, job: jest.Mocked<CyclotronV2DequeuedJob>): Promise<void> => {
        let callback: ((jobs: CyclotronV2DequeuedJob[]) => Promise<void>) | null = null
        const worker = {
            connect: jest.fn().mockImplementation((cb) => {
                callback = cb
                return Promise.resolve()
            }),
            disconnect: jest.fn().mockResolvedValue(undefined),
            isHealthy: jest.fn().mockReturnValue(true),
        } as unknown as CyclotronV2Worker
        const producer = { cancelJobs } as unknown as CyclotronV2JobProducer
        const consumer = new CdpCyclotronWorkerBatchResolve(
            hub,
            createCdpConsumerDeps(hub),
            worker,
            {} as HogFlowBatchPersonQueryService,
            {} as InternalFetchService,
            producer
        )
        await consumer.start()
        await callback!([job])
        await consumer.stop()
    }

    it('sweeps the children before acking a flagged resolver, so a page committed after the endpoint sweep still cancels', async () => {
        const cancelJobs = jest.fn().mockResolvedValue({ marked: 5, remaining: 0, done: true })
        const job = buildFlaggedJob()

        await startAndDeliver(cancelJobs, job)

        expect(cancelJobs).toHaveBeenCalledWith({ teamId: 7, functionId: 'flow-1', parentRunId: 'batch-1' })
        expect(job.cancel).toHaveBeenCalled()
        expect(job.reschedule).not.toHaveBeenCalled()
    })

    it('parks and retries instead of acking when the child sweep fails, so children cannot leak', async () => {
        const cancelJobs = jest.fn().mockRejectedValue(new Error('pg down'))
        const job = buildFlaggedJob()

        await startAndDeliver(cancelJobs, job)

        expect(job.cancel).not.toHaveBeenCalled()
        expect(job.reschedule).toHaveBeenCalled()
    })
})
