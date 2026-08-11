import { Team } from '~/types'

import { BatchResolverState } from '../services/hogflows/batch-resolver.types'
import { CyclotronJobInvocationHogFlow } from '../types'
import {
    CdpCyclotronWorkerBatchResolve,
    buildAccountHogFlowInvocation,
} from './cdp-cyclotron-worker-batch-resolve.consumer'

describe('CdpCyclotronWorkerBatchResolve', () => {
    const team = { id: 123, name: 'Test team' } as Team

    describe('buildAccountHogFlowInvocation', () => {
        it('carries the account group key and no person', () => {
            const invocation = buildAccountHogFlowInvocation({
                siteUrl: 'https://us.posthog.com',
                parentRunId: 'batch-job-1',
                team,
                hogFlowId: 'flow-1',
                flowVersion: 4,
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
    })

    describe('processOnePage run-level monitoring', () => {
        const BATCH_JOB_ID = 'batch-job-1'
        const HOG_FLOW_ID = 'flow-1'

        let consumer: CdpCyclotronWorkerBatchResolve
        let queueAppMetrics: jest.Mock
        let queueLifecycleRow: jest.Mock
        let dropQueuedRowsFor: jest.Mock
        let bulkCreateAndCheckIn: jest.Mock

        const state: BatchResolverState = {
            batchJobId: BATCH_JOB_ID,
            teamId: team.id,
            hogFlowId: HOG_FLOW_ID,
            cursor: null,
            filters: { properties: [] },
            maxAudienceSize: 100,
            totalEnqueued: 0,
            pagesProcessed: 0,
            attempts: 0,
            variables: {},
            startedAt: '2026-08-11T00:00:00.000Z',
        }

        const processPage = async (): Promise<void> =>
            await (consumer as any).processOnePage({ bulkCreateAndCheckIn, reschedule: jest.fn() }, state)

        beforeEach(() => {
            queueAppMetrics = jest.fn()
            queueLifecycleRow = jest.fn()
            dropQueuedRowsFor = jest.fn()
            bulkCreateAndCheckIn = jest.fn().mockResolvedValue(undefined)

            // The base constructor builds redis/valkey-backed services, so assemble the
            // instance directly — this exercises processOnePage without any live boundary.
            consumer = Object.create(CdpCyclotronWorkerBatchResolve.prototype)
            Object.assign(consumer, {
                config: { SITE_URL: 'https://us.posthog.com' },
                deps: { teamManager: { getTeam: jest.fn().mockResolvedValue(team) } },
                hogFlowManager: {
                    getHogFlow: jest.fn().mockResolvedValue({ id: HOG_FLOW_ID, version: 4, variables: [] }),
                },
                hogFlowBatchPersonQueryService: {
                    getBlastRadiusPersons: jest.fn().mockResolvedValue({
                        users_affected: ['person-1', 'person-2'],
                        cursor: null,
                        has_more: false,
                    }),
                },
                hogFunctionMonitoringService: { queueAppMetrics, queueLogs: jest.fn() },
                invocationResultsService: {
                    invocationResultsRowsService: { queueLifecycleRow, dropQueuedRowsFor },
                },
            })
        })

        it('counts each enrolled person as a triggered run against the batch job', async () => {
            await processPage()

            expect(queueAppMetrics).toHaveBeenCalledTimes(1)
            const [metrics, source] = queueAppMetrics.mock.calls[0]
            expect(source).toEqual('hog_flow')
            expect(metrics).toEqual([
                // Keyed on the batch job, not the workflow — that is where the batch metrics
                // view looks, and the workflow id would silently read as zero runs started.
                expect.objectContaining({
                    team_id: team.id,
                    app_source_id: BATCH_JOB_ID,
                    metric_kind: 'other',
                    metric_name: 'triggered',
                    count: 1,
                }),
                expect.objectContaining({ app_source_id: BATCH_JOB_ID, metric_name: 'triggered' }),
            ])
            // Run-level metrics carry no instance id; a step id here would hide them from the
            // started/in-progress counters, which filter on the empty instance.
            expect(metrics[0].instance_id).toBeUndefined()
        })

        it('records each enrolled person as a running invocation so parked runs are listable', async () => {
            await processPage()

            expect(queueLifecycleRow).toHaveBeenCalledTimes(2)
            for (const [invocation, status] of queueLifecycleRow.mock.calls) {
                expect(status).toEqual('running')
                expect(invocation.parentRunId).toEqual(BATCH_JOB_ID)
                expect(invocation.functionId).toEqual(HOG_FLOW_ID)
            }
        })

        it('stamps the enqueue time into the state that gets persisted', async () => {
            // queueLifecycleRow sets firstScheduledAt on the invocation, so it has to run before
            // the state is serialized onto the cyclotron job. If it runs after, the terminal row
            // written when the run wakes records the wake time and wins the argMax collapse.
            queueLifecycleRow.mockImplementation((invocation) => {
                invocation.state.firstScheduledAt = '2026-08-11 00:00:00.000000'
            })

            await processPage()

            const { newJobs } = bulkCreateAndCheckIn.mock.calls[0][0]
            for (const job of newJobs) {
                expect(job.state.toString()).toContain('firstScheduledAt')
            }
        })

        it('drops the queued rows when the page fails to commit', async () => {
            // The commit is atomic with the cursor advance, so a failure replays the whole page.
            // Rows left queued here would be written twice.
            bulkCreateAndCheckIn.mockRejectedValue(new Error('postgres is down'))

            await expect(processPage()).rejects.toThrow('postgres is down')

            const enrolled = queueLifecycleRow.mock.calls.map(([invocation]) => invocation.id)
            expect(dropQueuedRowsFor).toHaveBeenCalledWith(enrolled)
            expect(queueAppMetrics).not.toHaveBeenCalled()
        })
    })
})
