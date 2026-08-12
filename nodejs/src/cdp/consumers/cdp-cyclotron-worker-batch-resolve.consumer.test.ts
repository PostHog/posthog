import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { Team } from '~/types'

import { CdpOutput } from '../cdp-services'
import { HogFlow } from '../schema/hogflow'
import { BatchResolverState } from '../services/hogflows/batch-resolver.types'
import {
    HogInvocationResultRow,
    HogInvocationResultsService,
} from '../services/monitoring/hog-invocation-results.service'
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
                hogFlow: { id: 'flow-1', version: 4 } as HogFlow,
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
            // The processOnePage tests cover only the person path, so this is the one guard
            // that account children carry the shape marker the lifecycle rows classify by.
            expect(invocation.hogFlow.id).toEqual('flow-1')
        })
    })

    describe('processOnePage run-level monitoring', () => {
        const BATCH_JOB_ID = 'batch-job-1'
        const HOG_FLOW_ID = 'flow-1'

        let consumer: CdpCyclotronWorkerBatchResolve
        let queueAppMetrics: jest.Mock
        let outputs: jest.Mocked<IngestionOutputs<CdpOutput>>
        let rowsService: HogInvocationResultsService
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

        // The rows the real service produced on flush. Asserting on these rather than on mock
        // call args is what catches a misclassification: function_kind is derived structurally
        // inside the service ('hogFlow' in invocation), which a mocked service never evaluates.
        const producedRows = (): HogInvocationResultRow[] =>
            outputs.produce.mock.calls.map(
                ([, message]) => parseJSON(message.value!.toString('utf8')) as HogInvocationResultRow
            )

        beforeEach(() => {
            queueAppMetrics = jest.fn()
            bulkCreateAndCheckIn = jest.fn().mockResolvedValue(undefined)
            outputs = {
                produce: jest.fn().mockResolvedValue(undefined),
            } as unknown as jest.Mocked<IngestionOutputs<CdpOutput>>
            rowsService = new HogInvocationResultsService(outputs, { HOG_INVOCATION_RESULTS_ENABLED: true })

            // The base constructor builds redis/valkey-backed services, so assemble the
            // instance directly — this exercises processOnePage without any live boundary.
            // The rows service is real (only its produce boundary is mocked) because the
            // regressions to catch live inside it: how it classifies and stamps the
            // invocations this consumer builds.
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
                invocationResultsService: { invocationResultsRowsService: rowsService },
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

        it('records each enrolled person as a running hog_flow invocation so parked runs are listable', async () => {
            await processPage()
            await rowsService.flush()

            const rows = producedRows()
            expect(rows).toHaveLength(2)
            for (const row of rows) {
                // hog_flow, not hog_function: the workflow invocations API only reads rows with
                // function_kind = 'hog_flow', so a row under any other kind is invisible — the
                // exact blackout this PR exists to close.
                expect(row.function_kind).toEqual('hog_flow')
                expect(row.function_id).toEqual(HOG_FLOW_ID)
                expect(row.parent_run_id).toEqual(BATCH_JOB_ID)
                expect(row.status).toEqual('running')
            }
            expect(rows.map((row) => row.person_id).sort()).toEqual(['person-1', 'person-2'])
        })

        it('stamps the enqueue time into the state that gets persisted', async () => {
            // queueLifecycleRow sets firstScheduledAt on the invocation, so it has to run before
            // the state is serialized onto the cyclotron job. If it runs after — or if the
            // service does not recognize the invocation as a workflow — the terminal row written
            // when the run wakes records the wake time and wins the argMax collapse.
            await processPage()

            const { newJobs } = bulkCreateAndCheckIn.mock.calls[0][0]
            expect(newJobs).toHaveLength(2)
            for (const job of newJobs) {
                const persisted = parseJSON(job.state.toString('utf8'))
                expect(persisted.state.firstScheduledAt).toEqual(expect.any(String))
            }
        })

        it('drops the queued rows when the page fails to commit', async () => {
            // The commit is atomic with the cursor advance, so a failure replays the whole page.
            // Rows left queued here would be written twice.
            bulkCreateAndCheckIn.mockRejectedValue(new Error('postgres is down'))

            await expect(processPage()).rejects.toThrow('postgres is down')

            await rowsService.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
            expect(queueAppMetrics).not.toHaveBeenCalled()
        })
    })
})
