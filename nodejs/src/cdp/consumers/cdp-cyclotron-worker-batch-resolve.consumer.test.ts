import { DateTime } from 'luxon'

import { Team } from '~/types'

import { HogFlow } from '../schema/hogflow'
import type { CyclotronV2BulkCreateAndCheckInInput, CyclotronV2DequeuedJob } from '../services/cyclotron-v2'
import {
    BatchResolverState,
    deserializeResolverState,
    serializeResolverState,
} from '../services/hogflows/batch-resolver.types'
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
            expect(state.variables).toEqual({ greeting: 'hi' })
            expect(invocation.parentRunId).toEqual('batch-job-1')
            expect(invocation.queue).toEqual('hogflow')
            expect((invocation as any).person).toBeUndefined()
        })
    })

    describe('trigger masking', () => {
        const HOG_FLOW_ID = 'flow-1'
        const PERSON_IDS = ['person-a', 'person-b', 'person-c']
        const MASKING = { ttl: 7776000, hash: 'x', bytecode: ['_H', 1], threshold: null }

        const buildHogFlow = (masking: HogFlow['trigger_masking']): HogFlow =>
            ({
                id: HOG_FLOW_ID,
                team_id: team.id,
                status: 'active',
                variables: [],
                trigger: { type: 'batch', filters: {} },
                trigger_masking: masking,
            }) as unknown as HogFlow

        const state = (): BatchResolverState => ({
            batchJobId: 'batch-job-1',
            teamId: team.id,
            hogFlowId: HOG_FLOW_ID,
            filters: { properties: [], filter_test_accounts: false },
            variables: {},
            maxAudienceSize: 1000,
            cursor: null,
            totalEnqueued: 0,
            totalMasked: 0,
            pagesProcessed: 0,
            attempts: 0,
            startedAt: '2026-01-01T00:00:00.000Z',
        })

        /**
         * Resolver wired to stubs at its real boundaries (team/flow lookup, the audience query,
         * the masker, monitoring, and the cyclotron job) so one page can be processed without
         * Postgres or Redis.
         */
        const processOnePage = async (
            hogFlow: HogFlow,
            filterByMasking: jest.Mock
        ): Promise<{
            enqueuedPersonIds: (string | null)[]
            committedState: BatchResolverState
            appMetrics: any[]
            logs: any[]
        }> => {
            const appMetrics: any[] = []
            const logs: any[] = []
            let input: CyclotronV2BulkCreateAndCheckInInput | undefined

            const consumer = Object.create(CdpCyclotronWorkerBatchResolve.prototype) as any
            consumer.config = { SITE_URL: 'https://us.posthog.com' }
            consumer.deps = { teamManager: { getTeam: () => Promise.resolve(team) } }
            consumer.hogFlowManager = { getHogFlow: () => Promise.resolve(hogFlow) }
            consumer.hogFlowBatchPersonQueryService = {
                getBlastRadiusPersons: () =>
                    Promise.resolve({ users_affected: PERSON_IDS, cursor: null, has_more: false }),
            }
            consumer.hogMasker = { filterByMasking }
            consumer.hogFunctionMonitoringService = {
                queueAppMetrics: (metrics: any[]) => appMetrics.push(...metrics),
                queueLogs: (entries: any[]) => logs.push(...entries),
                flush: () => Promise.resolve(),
            }

            const job = {
                id: 'resolver-job-1',
                teamId: team.id,
                functionId: HOG_FLOW_ID,
                queueName: 'hogflow_batch_resolve',
                priority: 1,
                scheduled: DateTime.now(),
                created: DateTime.now(),
                parentRunId: 'batch-job-1',
                transitionCount: 0,
                state: serializeResolverState(state()),
                distinctId: null,
                personId: null,
                actionId: null,
                ack: () => Promise.resolve(),
                fail: () => Promise.resolve(),
                reschedule: () => Promise.resolve(),
                cancel: () => Promise.resolve(),
                heartbeat: () => Promise.resolve(),
                bulkCreateAndCheckIn: (received: CyclotronV2BulkCreateAndCheckInInput) => {
                    input = received
                    return Promise.resolve({ newJobIds: received.newJobs.map((newJob) => newJob.id) })
                },
            } as unknown as CyclotronV2DequeuedJob

            await consumer.processResolverJob(job)

            const disposition = input!.selfDisposition as { state: Buffer }
            return {
                enqueuedPersonIds: input!.newJobs.map((newJob) => newJob.personId ?? null),
                committedState: deserializeResolverState(disposition.state),
                appMetrics,
                logs,
            }
        }

        it('enqueues only the audience the masker allows through', async () => {
            // The reported incident: batch and scheduled enrollments bypassed masking entirely,
            // so a daily schedule re-enrolled its whole audience every run regardless of
            // trigger_masking, and each person re-entered the full drip.
            const filterByMasking = jest.fn((invocations: CyclotronJobInvocationHogFlow[]) =>
                Promise.resolve({
                    masked: invocations.filter((i) => i.person?.id !== 'person-b'),
                    notMasked: invocations.filter((i) => i.person?.id === 'person-b'),
                })
            )

            const result = await processOnePage(buildHogFlow(MASKING), filterByMasking)

            expect(result.enqueuedPersonIds).toEqual(['person-b'])
            expect(result.committedState.totalEnqueued).toBe(1)
            // Masked people never receive anything, so they must not spend the audience budget.
            expect(result.committedState.totalMasked).toBe(2)
            expect(result.appMetrics).toContainEqual(
                expect.objectContaining({ app_source_id: HOG_FLOW_ID, metric_name: 'masked', count: 2 })
            )
            expect(result.logs.map((log) => log.message).join('\n')).toContain('Masking suppressed 2 recipients')
        })

        it('leaves the audience untouched when the flow has no masking configured', async () => {
            const filterByMasking = jest.fn()

            const result = await processOnePage(buildHogFlow(null), filterByMasking)

            expect(filterByMasking).not.toHaveBeenCalled()
            expect(result.enqueuedPersonIds).toEqual(PERSON_IDS)
            expect(result.committedState.totalMasked).toBe(0)
            expect(result.logs.map((log) => log.message).join('\n')).not.toContain('Masking suppressed')
        })
    })
})
