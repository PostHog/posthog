import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { HogFlow } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createHogFlowInvocationContext, insertHogFlow } from '../_tests/fixtures-hogflows'
import { TRANSACTIONAL_EMAIL_EVENT } from '../services/hogflows/hogflow-sensitivity'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(5000)

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub

    beforeAll(async () => {
        hub = await createHub()
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    it('should set queue to email', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('email')
    })

    it('should extend CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
    })

    it.each([
        ['counts a job the transactional email API marked once, not again on its reschedule', true, [1, 0]],
        ['does not count a job without the mark', false, [0, 0]],
    ])('%s', async (_desc, marked, expectedTriggeredPerRun) => {
        const { team } = await createTestTeamFixture(hub.postgres)
        // The delay parks the run, so the second dequeue is a reschedule of the same job.
        const hogFlow: HogFlow = await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus('active')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        delay: { type: 'delay', config: { delay_duration: '1h' } },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'delay', type: 'continue' },
                        { from: 'delay', to: 'exit', type: 'continue' },
                    ],
                } as any)
                .build()
        )
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        const triggered = (result: CyclotronJobInvocationResult) =>
            result.metrics.filter((metric) => metric.metric_name === 'triggered')

        let job: CyclotronJobInvocation = {
            id: new UUIDT().toString(),
            teamId: team.id,
            functionId: hogFlow.id,
            queue: 'email',
            queuePriority: 0,
            state: createHogFlowInvocationContext({
                event: { distinct_id: 'distinct_A_1', properties: { to: 'user@example.com' } } as any,
                ...(marked ? { triggerMetricPending: true } : {}),
            }),
        }
        const triggeredPerRun: CyclotronJobInvocationResult['metrics'][] = []
        for (let run = 0; run < 2; run++) {
            const [result] = await worker.processInvocations([job])
            expect(result.finished).toBe(false)
            triggeredPerRun.push(triggered(result))
            // The job queue persists the result's state as JSON, and the next dequeue reads it back.
            job = { ...job, state: parseJSON(JSON.stringify(result.invocation.state)) }
        }

        expect(triggeredPerRun.map((metrics) => metrics.length)).toEqual(expectedTriggeredPerRun)
        expect(triggeredPerRun.flat()).toEqual(
            marked
                ? [
                      {
                          team_id: team.id,
                          app_source_id: hogFlow.id,
                          metric_kind: 'other',
                          metric_name: 'triggered',
                          count: 1,
                      },
                  ]
                : []
        )
    })

    it('closes a transactional send whose graded workflow version is newer than the database as a failed run', async () => {
        const { team } = await createTestTeamFixture(hub.postgres)
        const hogFlow: HogFlow = await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus('active')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [{ from: 'trigger', to: 'exit', type: 'continue' }],
                } as any)
                .build()
        )
        const jobQueue = createMockJobQueue()
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), jobQueue)
        const job: CyclotronJobInvocation = {
            id: new UUIDT().toString(),
            teamId: team.id,
            functionId: hogFlow.id,
            queue: 'email',
            queuePriority: 0,
            state: createHogFlowInvocationContext({
                event: { event: TRANSACTIONAL_EMAIL_EVENT, distinct_id: 'distinct_A_1', properties: {} } as any,
                triggerMetricPending: true,
                send: { tracking: { captureEngagement: false }, hogFlowVersion: hogFlow.version + 1 },
            }),
        }
        const produce = jest
            .spyOn(worker['invocationResultsService'].invocationResultsRowsService['outputs'], 'produce')
            .mockResolvedValue(undefined)
        const produced = (output: string): Record<string, unknown>[] =>
            produce.mock.calls
                .filter(([name]) => name === output)
                .map(([, message]) => parseJSON(message.value!.toString()))
        const resultsEnabled = hub.HOG_INVOCATION_RESULTS_ENABLED
        hub.HOG_INVOCATION_RESULTS_ENABLED = true

        try {
            const { invocationResults, backgroundTask } = await worker.processBatch([job])
            await backgroundTask

            expect(invocationResults).toEqual([
                expect.objectContaining({
                    finished: true,
                    error: `Workflow version ${hogFlow.version} is older than version ${hogFlow.version + 1}, which this send was checked against`,
                }),
            ])
            expect(invocationResults[0].metrics.map((metric) => metric.metric_name)).toEqual(['triggered'])
            expect(jobQueue.queueInvocationResults).toHaveBeenCalledWith(invocationResults)
            expect(produced('hog_invocation_results')).toEqual([
                expect.objectContaining({ invocation_id: job.id, function_kind: 'hog_flow', status: 'failed' }),
            ])
            expect(produced('email_status')).toEqual([
                expect.objectContaining({ message_id: job.id, status: 'failed' }),
            ])
        } finally {
            hub.HOG_INVOCATION_RESULTS_ENABLED = resultsEnabled
            produce.mockRestore()
        }
    })
})
