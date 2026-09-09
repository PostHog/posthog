import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { Team } from '~/types'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_FLOW_MASK_EXAMPLES } from '../_tests/examples'
import { CdpOutput } from '../cdp-services'
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
    // A non-default version, so the flowVersion assertion can't pass by accident.
    const hogFlow: HogFlow = { ...new FixtureHogFlowBuilder().withTeamId(team.id).build(), version: 4 }

    describe('buildAccountHogFlowInvocation', () => {
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

        // Two things key off this object. HogMaskerService.filterByMasking() only recognizes an
        // invocation as a hog flow invocation (and applies trigger_masking) when it carries a
        // `hogFlow`, and the invocation-results service classifies rows by the same shape — so a
        // regression here silently stops masking batch runs and drops their rows out of the
        // workflow invocations list, which filters on hog_flow.
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

    describe('processOnePage run-level monitoring', () => {
        const BATCH_JOB_ID = 'batch-job-1'

        let consumer: CdpCyclotronWorkerBatchResolve
        let queueAppMetrics: jest.Mock
        let outputs: jest.Mocked<IngestionOutputs<CdpOutput>>
        let rowsService: HogInvocationResultsService
        let bulkCreateAndCheckIn: jest.Mock
        let filterByMasking: jest.Mock
        let release: jest.Mock

        const state: BatchResolverState = {
            batchJobId: BATCH_JOB_ID,
            teamId: team.id,
            hogFlowId: hogFlow.id,
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

        const triggeredMetrics = (): any[] =>
            queueAppMetrics.mock.calls.flatMap(([metrics]) => metrics).filter((m) => m.metric_name === 'triggered')

        beforeEach(() => {
            queueAppMetrics = jest.fn()
            bulkCreateAndCheckIn = jest.fn().mockResolvedValue({ newJobIds: [] })
            release = jest.fn().mockResolvedValue(undefined)
            // Masking itself is covered by hog-masker.service.test.ts; stubbing the partition
            // here is what lets each case fix which runs are masked and assert how the consumer
            // routes them.
            filterByMasking = jest.fn((invocations) => ({ masked: [], notMasked: invocations, release }))
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
                hogFlowManager: { getHogFlow: jest.fn().mockResolvedValue(hogFlow) },
                hogFlowBatchPersonQueryService: {
                    getBlastRadiusPersons: jest.fn().mockResolvedValue({
                        users_affected: ['person-1', 'person-2'],
                        cursor: null,
                        has_more: false,
                    }),
                },
                hogMasker: { filterByMasking },
                hogFunctionMonitoringService: { queueAppMetrics, queueLogs: jest.fn() },
                invocationResultsService: { invocationResultsRowsService: rowsService },
            })
        })

        it('counts each enrolled person as a triggered run against the batch job', async () => {
            await processPage()

            const metrics = triggeredMetrics()
            expect(metrics).toHaveLength(2)
            for (const metric of metrics) {
                // Keyed on the batch job, not the workflow — that is where the batch metrics
                // view looks, and the workflow id would silently read as zero runs started.
                expect(metric.app_source_id).toEqual(BATCH_JOB_ID)
                expect(metric.team_id).toEqual(team.id)
                expect(metric.metric_kind).toEqual('other')
                expect(metric.count).toEqual(1)
                // Run-level metrics carry no instance id; a step id here would hide them from the
                // started/in-progress counters, which filter on the empty instance.
                expect(metric.instance_id).toBeUndefined()
            }
        })

        it('records each enrolled person as a running hog_flow invocation so parked runs are listable', async () => {
            await processPage()
            await rowsService.flush()

            const rows = producedRows()
            expect(rows).toHaveLength(2)
            for (const row of rows) {
                // hog_flow, not hog_function: the workflow invocations API only reads rows with
                // this kind, so a misclassified row is invisible even though it was written.
                expect(row.function_kind).toEqual('hog_flow')
                expect(row.function_id).toEqual(hogFlow.id)
                expect(row.parent_run_id).toEqual(BATCH_JOB_ID)
                expect(row.status).toEqual('running')
            }
        })

        it('stamps the enqueue time into the state that gets persisted', async () => {
            // The stamp is written onto the invocation by queueLifecycleRow, so it only lands in
            // cyclotron if that runs before the state is serialized. Out of order, the terminal
            // row written when the run wakes records the wake time and wins the argMax collapse.
            await processPage()

            const { newJobs } = bulkCreateAndCheckIn.mock.calls[0][0]
            expect(newJobs).toHaveLength(2)
            for (const job of newJobs) {
                expect(job.state.toString()).toContain('firstScheduledAt')
            }
        })

        it('leaves masked runs out of both the triggered count and the invocations list', async () => {
            // A masked run is never enqueued, so counting it as started would strand it in the
            // in-progress figure forever, and its running row would never get a terminal row.
            filterByMasking.mockImplementation((invocations: CyclotronJobInvocationHogFlow[]) => ({
                masked: [invocations[0]],
                notMasked: [invocations[1]],
                release,
            }))

            await processPage()
            await rowsService.flush()

            expect(triggeredMetrics()).toHaveLength(1)
            expect(producedRows()).toHaveLength(1)
        })

        it('drops the queued rows and releases the mask claims when the page fails to commit', async () => {
            // The commit is atomic with the cursor advance, so a failure replays the whole page.
            // Rows left queued here would be written twice.
            bulkCreateAndCheckIn.mockRejectedValue(new Error('postgres is down'))

            await expect(processPage()).rejects.toThrow('postgres is down')
            await rowsService.flush()

            expect(producedRows()).toHaveLength(0)
            expect(release).toHaveBeenCalledTimes(1)
            expect(triggeredMetrics()).toHaveLength(0)
        })

        it('terminates the resolver instead of scheduling another page when the check-in is refused by a cancel', async () => {
            // The engine refuses the page when a cancel flag landed mid-build: nothing
            // committed, so the queued running rows and mask claims must be undone (these
            // children will never run) and the resolver must terminate, not retry.
            bulkCreateAndCheckIn.mockResolvedValue({ newJobIds: [], cancelRequested: true })
            const cancel = jest.fn().mockResolvedValue(undefined)
            const reschedule = jest.fn()
            Object.assign(consumer, {
                hogFunctionMonitoringService: {
                    queueAppMetrics,
                    queueLogs: jest.fn(),
                    flush: jest.fn().mockResolvedValue(undefined),
                },
            })

            await (consumer as any).processOnePage({ bulkCreateAndCheckIn, reschedule, cancel }, state)
            await rowsService.flush()

            expect(producedRows()).toHaveLength(0)
            expect(release).toHaveBeenCalledTimes(1)
            expect(triggeredMetrics()).toHaveLength(0)
            expect(cancel).toHaveBeenCalledTimes(1)
            expect(reschedule).not.toHaveBeenCalled()
        })
    })

    describe('cancel-flagged resolver jobs', () => {
        it('terminates on dequeue without fetching a page, even when the state is unparseable', async () => {
            const getBlastRadiusPersons = jest.fn()
            const queueLogs = jest.fn()
            const flush = jest.fn().mockResolvedValue(undefined)
            const consumer = Object.create(CdpCyclotronWorkerBatchResolve.prototype)
            Object.assign(consumer, {
                hogFlowBatchPersonQueryService: { getBlastRadiusPersons },
                hogFunctionMonitoringService: { queueLogs, flush },
            })
            const cancel = jest.fn().mockResolvedValue(undefined)
            const job = {
                id: 'job-1',
                teamId: team.id,
                functionId: hogFlow.id,
                parentRunId: 'batch-job-1',
                cancelRequestedAt: DateTime.now(),
                // Unparseable on purpose: the cancel must not depend on state surviving
                // schema drift across deploys.
                state: Buffer.from('not json'),
                cancel,
            }

            await (consumer as any).processResolverJob(job)

            expect(cancel).toHaveBeenCalledTimes(1)
            expect(getBlastRadiusPersons).not.toHaveBeenCalled()
            // The stop is visible on the batch run's log stream, keyed by parent run id.
            expect(queueLogs).toHaveBeenCalledTimes(1)
            const [logs] = queueLogs.mock.calls[0]
            expect(logs[0].log_source_id).toEqual('batch-job-1')
            expect(flush).toHaveBeenCalled()
        })
    })
})
