import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { HogFlow } from '~/cdp/schema/hogflow'
import { InternalFetchService } from '~/common/services/internal-fetch'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger, serializeError } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { UUIDT } from '~/common/utils/utils'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginsServerConfig, Team } from '../../types'
import type { CyclotronV2DequeuedJob, CyclotronV2JobInit, CyclotronV2Worker } from '../services/cyclotron-v2'
import {
    BatchResolverState,
    MAX_RESOLVER_ATTEMPTS,
    deserializeResolverState,
    serializeResolverState,
} from '../services/hogflows/batch-resolver.types'
import { HogFlowBatchPersonQueryService } from '../services/hogflows/hogflow-batch-person-query.service'
import { invocationToV2JobInit } from '../services/job-queue/job-queue-postgres-v2'
import { CyclotronJobInvocationHogFlow } from '../types'
import {
    convertAccountBatchHogFlowRequestToHogFunctionInvocationGlobals,
    convertBatchHogFlowRequestToHogFunctionInvocationGlobals,
    logEntry,
} from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterBatchHogFlowTriggerFailed } from './metrics'

const RETRY_BACKOFF_MS = 5_000

const counterBatchHogFlowAudienceTruncated = new Counter({
    name: 'cdp_batch_hog_flow_audience_truncated',
    help: 'A batch hog flow run hit the per-team maxAudienceSize cap before finishing the audience',
    labelNames: ['hog_flow_id'],
})

const counterBatchHogFlowResolverPagesProcessed = new Counter({
    name: 'cdp_batch_hog_flow_resolver_pages_processed',
    help: 'Total pages processed by the cyclotron-based batch resolver',
    labelNames: ['outcome'], // success | fetch_failure | terminal_write_failure | invalid_state
})

const counterBatchHogFlowResolverJobs = new Counter({
    name: 'cdp_batch_hog_flow_resolver_jobs',
    help: 'Batch hog flow resolver jobs by lifecycle outcome',
    labelNames: ['outcome'], // started | completed | failed | canceled
})

/**
 * State machine carried in `cyclotron_jobs.state` per resolver job:
 *   cursor=null, pendingTerminal=undefined → fetch first page
 *   cursor=X,    pendingTerminal=undefined → fetch next page
 *   pendingTerminal='completed'|'failed'   → PUT Django, ack on 200
 *
 * Resolver only acks after terminal Django write succeeds — Django down
 * means the job parks via cyclotron retry, no progress is lost.
 */
export class CdpCyclotronWorkerBatchResolve extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpCyclotronWorkerBatchResolve'

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        private cyclotronWorker: CyclotronV2Worker,
        private hogFlowBatchPersonQueryService: HogFlowBatchPersonQueryService,
        private internalFetchService: InternalFetchService
    ) {
        super(config, deps)
    }

    public override async start(): Promise<void> {
        await super.start()

        await this.cyclotronWorker.connect(async (jobs) => {
            for (const job of jobs) {
                await this.processResolverJob(job)
            }
        })

        logger.info('🔁', `${this.name} started`)
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `${this.name} stopping...`)
        await this.cyclotronWorker.disconnect()
        await super.stop()
        logger.info('💤', `${this.name} stopped`)
    }

    public isHealthy(): HealthCheckResult {
        return this.cyclotronWorker.isHealthy()
            ? new HealthCheckResultOk()
            : new HealthCheckResultError('Cyclotron worker is not healthy', { name: this.name })
    }

    private async processResolverJob(job: CyclotronV2DequeuedJob): Promise<void> {
        // Checked before state deserialization so a cancel lands even on a job whose state
        // this deploy can no longer parse. `parentRunId` carries the batch job id
        // independently of state, so the log still keys to the run.
        if (job.cancelRequestedAt) {
            await this.cancelResolverJob(job)
            return
        }

        let state: BatchResolverState
        try {
            state = deserializeResolverState(job.state)
        } catch (err) {
            // Schema drift, corrupted state, or a job from an incompatible
            // older deploy. None should happen in steady state — alert on
            // the counter so we notice fast.
            counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'invalid_state' }).inc()
            counterBatchHogFlowResolverJobs.labels({ outcome: 'failed' }).inc()
            logger.error('🔴', `${this.name} - invalid resolver state, failing job`, {
                jobId: job.id,
                teamId: job.teamId,
                functionId: job.functionId,
                parentRunId: job.parentRunId,
                error: serializeError(err),
            })
            captureException(err, {
                tags: { resolver_error: 'invalid_state', jobId: job.id, parentRunId: job.parentRunId ?? '' },
            })
            await job.fail()
            return
        }

        // First-dequeue detection: the initial cyclotron invocation of a batch
        // resolver job arrives with cursor=null, no pending terminal, zero
        // pages processed, and zero attempts. `attempts` is required in the
        // guard because a first-page fetch failure reschedules with the same
        // cursor/pagesProcessed/pendingTerminal but bumps attempts — without
        // it, `started` would fire again on every retry of the first page.
        if (!state.pendingTerminal && state.cursor === null && state.pagesProcessed === 0 && state.attempts === 0) {
            counterBatchHogFlowResolverJobs.labels({ outcome: 'started' }).inc()
        }

        try {
            if (state.pendingTerminal) {
                try {
                    await this.processTerminalWrite(job, state)
                } catch (err) {
                    counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'terminal_write_failure' }).inc()
                    logger.error('🔴', `${this.name} - unexpected error in processTerminalWrite`, {
                        batchJobId: state.batchJobId,
                        pendingTerminal: state.pendingTerminal,
                        error: serializeError(err),
                    })
                    captureException(err, {
                        tags: { resolver_error: 'terminal_write_unhandled', batchJobId: state.batchJobId },
                    })
                    // Don't ack — leave the job parked so cyclotron's stall recovery
                    // picks it up and another worker can retry.
                    await job.reschedule({ scheduledAt: new Date(Date.now() + RETRY_BACKOFF_MS) })
                }
                return
            }

            if (state.totalEnqueued >= state.maxAudienceSize) {
                await this.transitionToTruncatedTerminal(job, state)
                return
            }

            await this.processOnePage(job, state)
        } finally {
            // Flush monitoring every dequeue, not just on terminal-write. Non-terminal
            // paths (truncation log queued in processOnePage, failure log in
            // transitionToFailedTerminal) would otherwise wait for a later terminal
            // dequeue — under multi-replica that's a different worker, and under a
            // restart it's gone entirely.
            await Promise.all([
                this.hogFunctionMonitoringService.flush(),
                this.invocationResultsService.invocationResultsRowsService.flush(),
            ]).catch((err) => {
                logger.warn('⚠️', `${this.name} - failed to flush monitoring after resolver dequeue`, {
                    error: serializeError(err),
                })
            })
        }
    }

    /**
     * Terminate a cancel-flagged resolver job: no further pages, and no terminal status
     * PUT — Django flips the batch job's status itself as part of the cancel request, and
     * the internal status endpoint absorbs terminal states, so a racing completion still
     * resolves consistently. The log lands on the batch run's log stream so the stop is
     * visible next to its runs. Flushes monitoring itself because the cancel paths return
     * before processResolverJob's finally-flush.
     */
    private async cancelResolverJob(job: CyclotronV2DequeuedJob): Promise<void> {
        counterBatchHogFlowResolverJobs.labels({ outcome: 'canceled' }).inc()
        this.hogFunctionMonitoringService.queueLogs(
            [
                {
                    team_id: job.teamId,
                    log_source: 'hog_flow',
                    log_source_id: job.parentRunId ?? job.functionId ?? '',
                    instance_id: job.parentRunId ?? job.id,
                    ...logEntry('info', 'Batch run canceled. The remaining audience will not receive this workflow.'),
                },
            ],
            'hog_flow'
        )
        await this.hogFunctionMonitoringService.flush().catch((err) => {
            logger.warn('⚠️', `${this.name} - failed to flush monitoring after resolver cancel`, {
                error: serializeError(err),
            })
        })
        await job.cancel()
        logger.info('🛑', `${this.name} - resolver job canceled`, {
            jobId: job.id,
            parentRunId: job.parentRunId,
        })
    }

    /**
     * Fetch one page of audience and atomically enqueue children + advance state.
     * On fetch failure, retries via cyclotron reschedule with backoff — cursor
     * is preserved in state so the page replays cleanly.
     */
    private async processOnePage(job: CyclotronV2DequeuedJob, state: BatchResolverState): Promise<void> {
        const [team, hogFlow] = await Promise.all([
            this.deps.teamManager.getTeam(state.teamId),
            this.hogFlowManager.getHogFlow(state.hogFlowId),
        ])

        if (!team || !hogFlow) {
            logger.error('🔴', `${this.name} - missing team or hogflow, failing resolver`, {
                teamId: state.teamId,
                hogFlowId: state.hogFlowId,
                batchJobId: state.batchJobId,
            })
            counterBatchHogFlowTriggerFailed.labels({ hog_flow_id: state.hogFlowId, reason: 'missing_entity' }).inc()
            await this.transitionToFailedTerminal(job, state, 'Workflow or team was deleted mid-run')
            return
        }

        const isAccountAudience = state.filters.audience_type === 'accounts'

        // Normalized page shape so budget/truncation/state logic below stays single-path.
        let page: { ids: string[]; cursor: string | null; has_more: boolean; accountGroupType?: string }
        try {
            if (isAccountAudience) {
                const accountPage = await instrumentFn('cdpBatchResolve.getAccountAudiencePage', () =>
                    this.hogFlowBatchPersonQueryService.getAccountAudiencePage(team, state.filters, state.cursor)
                )
                page = {
                    ids: accountPage.accounts,
                    cursor: accountPage.cursor,
                    has_more: accountPage.has_more,
                    accountGroupType: accountPage.group_type,
                }
            } else {
                const personsPage = await instrumentFn('cdpBatchResolve.getBlastRadiusPersons', () =>
                    this.hogFlowBatchPersonQueryService.getBlastRadiusPersons(
                        team,
                        state.filters,
                        state.groupTypeIndex,
                        state.cursor,
                        state.dedupeKey
                    )
                )
                page = { ids: personsPage.users_affected, cursor: personsPage.cursor, has_more: personsPage.has_more }
            }
        } catch (err) {
            counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'fetch_failure' }).inc()
            const nextAttempts = state.attempts + 1
            if (nextAttempts >= MAX_RESOLVER_ATTEMPTS) {
                logger.error(
                    '🔴',
                    `${this.name} - page fetch failed permanently after ${MAX_RESOLVER_ATTEMPTS} attempts`,
                    {
                        batchJobId: state.batchJobId,
                        cursor: state.cursor,
                        pagesProcessed: state.pagesProcessed,
                        error: serializeError(err),
                    }
                )
                await this.transitionToFailedTerminal(
                    job,
                    state,
                    `Audience fetch failed permanently after ${MAX_RESOLVER_ATTEMPTS} attempts`
                )
                return
            }
            logger.warn('⚠️', `${this.name} - page fetch failed, will retry`, {
                batchJobId: state.batchJobId,
                cursor: state.cursor,
                pagesProcessed: state.pagesProcessed,
                attempts: nextAttempts,
                error: serializeError(err),
            })
            const retryState: BatchResolverState = { ...state, attempts: nextAttempts }
            await job.reschedule({
                scheduledAt: new Date(Date.now() + RETRY_BACKOFF_MS),
                state: serializeResolverState(retryState),
            })
            return
        }

        // Hard cap: truncate the crossing page so totalEnqueued never exceeds
        // maxAudienceSize. Without this, a page can push us over the cap by
        // up to one full page's worth of children before the next dequeue
        // notices and stops.
        const remainingBudget = Math.max(0, state.maxAudienceSize - state.totalEnqueued)
        const eligibleIds = page.ids.slice(0, remainingBudget)
        const pageTruncated = eligibleIds.length < page.ids.length

        const defaultVariables = mergeDefaultVariables(hogFlow.variables, state.variables)
        const builtInvocations: CyclotronJobInvocationHogFlow[] = eligibleIds.map((id) =>
            isAccountAudience
                ? buildAccountHogFlowInvocation({
                      siteUrl: this.config.SITE_URL,
                      parentRunId: state.batchJobId,
                      team,
                      hogFlow,
                      externalId: id,
                      groupType: page.accountGroupType ?? '',
                      defaultVariables,
                  })
                : buildHogFlowInvocation({
                      siteUrl: this.config.SITE_URL,
                      parentRunId: state.batchJobId,
                      team,
                      hogFlow,
                      personId: id,
                      defaultVariables,
                  })
        )

        // Batch-built invocations skip the event-triggered pipeline entirely, so
        // trigger_masking has to be applied here explicitly — otherwise a workflow
        // with a masking TTL re-enrolls the same audience on every scheduled run.
        const { masked, notMasked, release } = await this.hogMasker.filterByMasking(builtInvocations)

        // Only the unmasked runs get a lifecycle row: a masked one is never enqueued, so a
        // `running` row for it would sit in the invocations list forever with no terminal row.
        //
        // Queued before serializing, because queueLifecycleRow stamps `state.firstScheduledAt`
        // on the invocation and the terminal row written after the run wakes has to inherit it —
        // otherwise that row records the wake time and wins the ReplacingMergeTree collapse,
        // mislabeling when the run started.
        for (const invocation of notMasked) {
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        const children: CyclotronV2JobInit[] = notMasked.map((invocation) => invocationToV2JobInit(invocation))

        const newState: BatchResolverState = {
            ...state,
            cursor: page.cursor,
            totalEnqueued: state.totalEnqueued + eligibleIds.length,
            pagesProcessed: state.pagesProcessed + 1,
            attempts: 0, // reset on successful page commit
        }
        if (!page.has_more || pageTruncated) {
            newState.pendingTerminal = 'completed'
        }

        let checkIn: { newJobIds: string[]; cancelRequested?: boolean }
        try {
            checkIn = await job.bulkCreateAndCheckIn({
                newJobs: children,
                selfDisposition: {
                    kind: 'reschedule',
                    scheduledAt: new Date(),
                    state: serializeResolverState(newState),
                },
            })
        } catch (err) {
            // The mask claims are already in Redis, but the page didn't commit — the
            // stall-recovery replay of this cursor would see the whole page as masked
            // and silently drop it. Undo the claims so the replay re-enrolls cleanly.
            await release()
            // Same reasoning for the lifecycle rows queued above: the replay re-queues them,
            // so leaving these would write each run's `running` row twice.
            this.invocationResultsService.invocationResultsRowsService.dropQueuedRowsFor(
                notMasked.map((invocation) => invocation.id)
            )
            throw err
        }

        if (checkIn.cancelRequested) {
            // A cancel flag landed while this page was being built, so the check-in was
            // refused and nothing committed. Undo the mask claims and queued `running`
            // rows exactly like the failure path — these children will never run — then
            // terminate the resolver instead of scheduling another page.
            await release()
            this.invocationResultsService.invocationResultsRowsService.dropQueuedRowsFor(
                notMasked.map((invocation) => invocation.id)
            )
            await this.cancelResolverJob(job)
            return
        }

        // Queued only after a successful commit: a failed page is replayed, so metrics
        // emitted for it would double-count once the replay re-evaluates masking.
        if (masked.length) {
            this.hogFunctionMonitoringService.queueAppMetrics(
                masked.map((item) => ({
                    team_id: item.teamId,
                    app_source_id: item.functionId,
                    metric_kind: 'other',
                    metric_name: 'masked',
                    count: 1,
                    app_source_version: { id: item.hogFlow.id, version: item.hogFlow.version },
                })),
                'hog_flow'
            )
        }

        // Mirrors the `triggered` metric the realtime trigger path emits per invocation, so
        // batch runs count towards "workflows started" (and the derived in-progress count).
        // Masked runs are excluded: counting one as started would leave it in progress forever,
        // since it never runs and so never records a terminal `succeeded`.
        // Keyed on the batch job id like every other metric a batch run emits; `instance_id`
        // is left unset because this is a run-level, not a step-level, metric.
        this.hogFunctionMonitoringService.queueAppMetrics(
            notMasked.map((invocation) => ({
                team_id: invocation.teamId,
                app_source_id: invocation.parentRunId ?? hogFlow.id,
                metric_kind: 'other' as const,
                metric_name: 'triggered' as const,
                count: 1,
                app_source_version: { id: hogFlow.id, version: hogFlow.version },
            })),
            'hog_flow'
        )

        if (pageTruncated) {
            this.emitTruncationLog(newState)
        }

        counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'success' }).inc()

        logger.info(
            '📝',
            `${this.name} - processed page for batch ${state.batchJobId}: ${children.length} ${isAccountAudience ? 'accounts' : 'persons'} enqueued, ${masked.length} masked (${newState.totalEnqueued} total resolved, ${newState.pagesProcessed} pages)`
        )
    }

    private emitTruncationLog(state: BatchResolverState): void {
        counterBatchHogFlowAudienceTruncated.labels({ hog_flow_id: state.hogFlowId }).inc()
        const message = `Audience reached the max cap of ${state.maxAudienceSize}, ${state.totalEnqueued} persons enqueued; the remainder did not receive this workflow.`
        logger.warn('⚠️', `${this.name} - audience truncated`, {
            batchJobId: state.batchJobId,
            totalEnqueued: state.totalEnqueued,
            maxAudienceSize: state.maxAudienceSize,
        })
        this.hogFunctionMonitoringService.queueLogs(
            [
                {
                    team_id: state.teamId,
                    log_source: 'hog_flow',
                    log_source_id: state.batchJobId,
                    instance_id: state.batchJobId,
                    ...logEntry('warn', message),
                },
            ],
            'hog_flow'
        )
    }

    private async transitionToTruncatedTerminal(job: CyclotronV2DequeuedJob, state: BatchResolverState): Promise<void> {
        this.emitTruncationLog(state)
        const newState: BatchResolverState = {
            ...state,
            pendingTerminal: 'completed',
            attempts: 0, // give the terminal write a fresh retry budget
        }
        await job.reschedule({ scheduledAt: new Date(), state: serializeResolverState(newState) })
    }

    private async transitionToFailedTerminal(
        job: CyclotronV2DequeuedJob,
        state: BatchResolverState,
        reasonMessage: string
    ): Promise<void> {
        this.hogFunctionMonitoringService.queueLogs(
            [
                {
                    team_id: state.teamId,
                    log_source: 'hog_flow',
                    log_source_id: state.batchJobId,
                    instance_id: state.batchJobId,
                    ...logEntry('error', `Batch resolver failed: ${reasonMessage}`),
                },
            ],
            'hog_flow'
        )

        const newState: BatchResolverState = {
            ...state,
            pendingTerminal: 'failed',
            attempts: 0, // give the terminal write a fresh retry budget
        }
        await job.reschedule({ scheduledAt: new Date(), state: serializeResolverState(newState) })
    }

    private async processTerminalWrite(job: CyclotronV2DequeuedJob, state: BatchResolverState): Promise<void> {
        if (!state.pendingTerminal) {
            await job.fail()
            return
        }

        try {
            await this.putBatchJobStatus(state.teamId, state.batchJobId, state.pendingTerminal)
        } catch (err) {
            counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'terminal_write_failure' }).inc()
            const nextAttempts = state.attempts + 1
            if (nextAttempts >= MAX_RESOLVER_ATTEMPTS) {
                counterBatchHogFlowResolverJobs.labels({ outcome: 'failed' }).inc()
                logger.error(
                    '🔴',
                    `${this.name} - terminal status write failed permanently after ${MAX_RESOLVER_ATTEMPTS} attempts; failing job`,
                    {
                        batchJobId: state.batchJobId,
                        pendingTerminal: state.pendingTerminal,
                        error: serializeError(err),
                    }
                )
                await job.fail()
                return
            }
            logger.warn('⚠️', `${this.name} - terminal status write failed, will retry`, {
                batchJobId: state.batchJobId,
                pendingTerminal: state.pendingTerminal,
                attempts: nextAttempts,
                error: serializeError(err),
            })
            const retryState: BatchResolverState = { ...state, attempts: nextAttempts }
            await job.reschedule({
                scheduledAt: new Date(Date.now() + RETRY_BACKOFF_MS),
                state: serializeResolverState(retryState),
            })
            return
        }

        counterBatchHogFlowResolverJobs
            .labels({ outcome: state.pendingTerminal === 'completed' ? 'completed' : 'failed' })
            .inc()

        // Monitoring flush happens in processResolverJob's finally block so every
        // dequeue clears its own queued logs/metrics, not just terminal writes.
        await job.ack()
        logger.info('✅', `${this.name} - batch ${state.batchJobId} → ${state.pendingTerminal}`, {
            totalEnqueued: state.totalEnqueued,
            pagesProcessed: state.pagesProcessed,
        })
    }

    private async putBatchJobStatus(teamId: number, batchJobId: string, status: 'completed' | 'failed'): Promise<void> {
        const urlPath = `/api/projects/${teamId}/internal/hog_flows/batch_jobs/${batchJobId}/status` as const

        const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
            urlPath,
            fetchParams: {
                method: 'PUT',
                body: JSON.stringify({ status }),
                timeoutMs: 10_000,
            },
        })

        if (fetchError) {
            throw fetchError
        }
        if (!fetchResponse) {
            throw new Error('Empty response from Django')
        }
        if (fetchResponse.status !== 200) {
            const errorText = await fetchResponse.text()
            throw new Error(`Django returned ${fetchResponse.status}: ${errorText}`)
        }
    }
}

function mergeDefaultVariables(
    hogFlowVariables: Array<{ key: string; default?: unknown }> | undefined | null,
    runOverrides: Record<string, unknown>
): Record<string, unknown> {
    const defaults: Record<string, unknown> = {}
    for (const variable of hogFlowVariables ?? []) {
        defaults[variable.key] = variable.default ?? null
    }
    return { ...defaults, ...runOverrides }
}

// Mirrors buildHogFlowInvocation for an account audience: the invocation carries the
// account's group key (via $groups and distinct_id) and no person at all — the hogflow
// worker skips person resolution for account audiences.
export function buildAccountHogFlowInvocation(params: {
    siteUrl: string
    parentRunId: string
    team: Team
    hogFlow: HogFlow
    externalId: string
    groupType: string
    defaultVariables: Record<string, unknown>
}): CyclotronJobInvocationHogFlow {
    const invocationGlobals = convertAccountBatchHogFlowRequestToHogFunctionInvocationGlobals({
        team: params.team,
        externalId: params.externalId,
        groupType: params.groupType,
        siteUrl: params.siteUrl,
    })

    const filterGlobals = convertToHogFunctionFilterGlobal(invocationGlobals)

    return {
        id: new UUIDT().toString(),
        state: {
            event: invocationGlobals.event,
            accountAudience: true,
            actionStepCount: 0,
            variables: params.defaultVariables,
            // Same reason as createHogFlowInvocation: a broadcast's conversions arrive long after
            // the send, so they attribute to the version that sent, not the one live by then.
            flowVersion: params.hogFlow.version,
        },
        teamId: params.team.id,
        functionId: params.hogFlow.id,
        // In-memory only (persistence serializes just `state`), but load-bearing for
        // monitoring: the invocation-results service classifies by shape (`'hogFlow' in
        // invocation`), and a row not classified as hog_flow never shows up in the
        // workflow invocations list.
        hogFlow: params.hogFlow,
        parentRunId: params.parentRunId,
        filterGlobals,
        queue: 'hogflow' as const,
        queuePriority: 1,
        queueScheduledAt: DateTime.now(),
    }
}

// Mirrors `createHogFlowInvocation` from the legacy Kafka consumer so children
// land in cyclotron_jobs looking the same regardless of dispatch path.
function buildHogFlowInvocation(params: {
    siteUrl: string
    parentRunId: string
    team: Team
    hogFlow: HogFlow
    personId: string
    defaultVariables: Record<string, unknown>
}): CyclotronJobInvocationHogFlow {
    const invocationGlobals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
        team: params.team,
        personId: params.personId,
        siteUrl: params.siteUrl,
    })

    const filterGlobals = convertToHogFunctionFilterGlobal(invocationGlobals)

    return {
        id: new UUIDT().toString(),
        state: {
            event: invocationGlobals.event,
            personId: params.personId,
            actionStepCount: 0,
            variables: params.defaultVariables,
            // Same reason as createHogFlowInvocation: a broadcast's conversions arrive days after
            // the send, so they have to attribute to the version that sent, not the one live then.
            flowVersion: params.hogFlow.version,
        },
        teamId: params.team.id,
        functionId: params.hogFlow.id,
        // See buildAccountHogFlowInvocation: in-memory only, but drives the shape-based
        // hog_flow classification of the `running` lifecycle rows.
        hogFlow: params.hogFlow,
        parentRunId: params.parentRunId,
        person: invocationGlobals.person,
        filterGlobals,
        queue: 'hogflow' as const,
        queuePriority: 1,
        queueScheduledAt: DateTime.now(),
    }
}
