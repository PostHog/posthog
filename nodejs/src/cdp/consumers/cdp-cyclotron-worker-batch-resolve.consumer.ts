import { DateTime } from 'luxon'

import { InternalFetchService } from '~/common/services/internal-fetch'
import { instrumentFn } from '~/common/tracing/tracing-utils'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginsServerConfig } from '../../types'
import { logger, serializeError } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { UUIDT } from '../../utils/utils'
import { CyclotronV2DequeuedJob, CyclotronV2JobInit, CyclotronV2Worker } from '../services/cyclotron-v2'
import {
    BatchResolverState,
    HOGFLOW_BATCH_RESOLVE_QUEUE,
    deserializeResolverState,
    serializeResolverState,
} from '../services/hogflows/batch-resolver.types'
import { HogFlowBatchPersonQueryService } from '../services/hogflows/hogflow-batch-person-query.service'
import { invocationToV2JobInit } from '../services/job-queue/job-queue-postgres-v2'
import { CyclotronJobInvocation } from '../types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals, logEntry } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import {
    counterBatchHogFlowAudienceTruncated,
    counterBatchHogFlowResolverPagesProcessed,
    counterBatchHogFlowTriggerFailed,
} from './metrics'

/**
 * How long to wait between cyclotron-level retries when an external call
 * fails. Short enough to keep batches making progress; long enough to give
 * a transient blip a chance to resolve.
 */
const RETRY_BACKOFF_MS = 5_000

/**
 * Per-batch resolver consumer.
 *
 * Dequeues one resolver job at a time from the `hogflow_batch_resolve` queue.
 * Each dequeue does one unit of work — either one page of audience resolution
 * (fetch persons → enqueue 500 child workflow invocations atomically with
 * its own state update) or one terminal write to Django.
 *
 * State machine (carried in cyclotron_jobs.state for each resolver job):
 *   cursor=null, pendingTerminal=undefined → fetch first page
 *   cursor=X,    pendingTerminal=undefined → fetch next page
 *   pendingTerminal='completed'|'failed'   → attempt Django PUT, ack on 200
 *
 * Failure handling is via cyclotron retry semantics (`reschedule` with
 * backoff). The resolver only acks when terminal Django write succeeds, so
 * no progress is lost on transient failures.
 */
export class CdpCyclotronWorkerBatchResolve extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpCyclotronWorkerBatchResolve'

    private cyclotronWorker: CyclotronV2Worker
    // Shared fetch service: same base URL + secret across audience-fetch
    // and terminal-status calls, constructed once.
    private internalFetchService: InternalFetchService
    // Public for test injection: integration tests provide a mock that returns
    // synthetic person pages without talking to Django/ClickHouse.
    public hogFlowBatchPersonQueryService: HogFlowBatchPersonQueryService
    // Public for test injection: integration tests override this to simulate
    // Django outages / 5xx without standing up a real Django process.
    public putBatchJobStatusFn: (
        teamId: number,
        batchJobId: string,
        status: 'completed' | 'failed',
        truncatedAtCount: number | undefined
    ) => Promise<void> = (teamId, batchJobId, status, truncatedAtCount) =>
        this.putBatchJobStatus(teamId, batchJobId, status, truncatedAtCount)

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)

        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CYCLOTRON_NODE_DATABASE_URL is required for CdpCyclotronWorkerBatchResolve')
        }

        this.cyclotronWorker = new CyclotronV2Worker({
            pool: {
                dbUrl: config.CYCLOTRON_NODE_DATABASE_URL,
                maxConnections: 10,
            },
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            batchMaxSize: 1, // process one resolver job at a time per worker
            pollDelayMs: 100,
        })

        this.internalFetchService = new InternalFetchService(config.INTERNAL_API_BASE_URL, config.INTERNAL_API_SECRET)
        this.hogFlowBatchPersonQueryService = new HogFlowBatchPersonQueryService(this.internalFetchService)
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

    /**
     * Single resolver job execution: either process one page or attempt the
     * terminal Django write. All atomicity is handled by the cyclotron
     * `bulkCreateAndCheckIn` primitive — partial state can't leak past a
     * worker crash because the child enqueue and state update are one TX.
     *
     * Public for testability: integration tests dequeue a job through a real
     * CyclotronV2Worker and then call this directly with the dequeued job
     * so they can assert state transitions deterministically without racing
     * the consumer loop.
     */
    public async processResolverJob(job: CyclotronV2DequeuedJob): Promise<void> {
        let state: BatchResolverState
        try {
            state = deserializeResolverState(job.state)
        } catch (err) {
            logger.error('🔴', `${this.name} - invalid resolver state, failing job`, {
                jobId: job.id,
                error: serializeError(err),
            })
            captureException(err)
            await job.fail()
            return
        }

        // Terminal-write phase: previous page set pendingTerminal; just push status to Django.
        if (state.pendingTerminal) {
            await this.processTerminalWrite(job, state)
            return
        }

        // Truncation: audience cap reached. Surface to customer + flip into terminal-write phase.
        if (state.totalEnqueued >= state.maxAudienceSize) {
            await this.transitionToTruncatedTerminal(job, state)
            return
        }

        // Normal page processing.
        await this.processOnePage(job, state)
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
            // Team or HogFlow disappeared (deleted?). Terminate the resolver run.
            logger.error('🔴', `${this.name} - missing team or hogflow, failing resolver`, {
                teamId: state.teamId,
                hogFlowId: state.hogFlowId,
                batchJobId: state.batchJobId,
            })
            counterBatchHogFlowTriggerFailed.labels({ hog_flow_id: state.hogFlowId, reason: 'missing_entity' }).inc()
            await this.transitionToFailedTerminal(job, state, 'Workflow or team was deleted mid-run')
            return
        }

        let page
        try {
            page = await instrumentFn('cdpBatchResolve.getBlastRadiusPersons', () =>
                this.hogFlowBatchPersonQueryService.getBlastRadiusPersons(
                    team,
                    state.filters,
                    state.groupTypeIndex,
                    state.cursor
                )
            )
        } catch (err) {
            // Transient ClickHouse / Django blip — cyclotron retry semantics
            // resume from the same cursor.
            logger.warn('⚠️', `${this.name} - page fetch failed, will retry`, {
                batchJobId: state.batchJobId,
                cursor: state.cursor,
                pagesProcessed: state.pagesProcessed,
                error: serializeError(err),
            })
            counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'fetch_failure' }).inc()
            await job.reschedule({ scheduledAt: new Date(Date.now() + RETRY_BACKOFF_MS) })
            return
        }

        // Build child invocations for this page.
        const defaultVariables = mergeDefaultVariables(hogFlow.variables, state.variables)
        const children: CyclotronV2JobInit[] = page.users_affected.map((personId) =>
            invocationToV2JobInit(
                buildHogFlowInvocation({
                    siteUrl: this.config.SITE_URL,
                    parentRunId: state.batchJobId,
                    teamId: team.id,
                    hogFlowId: hogFlow.id,
                    personId,
                    defaultVariables,
                })
            )
        )

        // Compute new state.
        const newState: BatchResolverState = {
            ...state,
            cursor: page.cursor,
            totalEnqueued: state.totalEnqueued + children.length,
            pagesProcessed: state.pagesProcessed + 1,
        }

        // Is this the last page (audience exhausted)? If so, flip into terminal-write phase.
        const isLastPage = !page.has_more
        if (isLastPage) {
            newState.pendingTerminal = 'completed'
        }

        // Atomic: enqueue children + advance state (or transition into pendingTerminal).
        await job.bulkCreateAndCheckIn({
            newJobs: children,
            selfDisposition: {
                kind: 'reschedule',
                scheduledAt: new Date(),
                state: serializeResolverState(newState),
            },
        })

        counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'success' }).inc()

        logger.info(
            '📝',
            `${this.name} - processed page for batch ${state.batchJobId}: ${children.length} persons (${newState.totalEnqueued} total, ${newState.pagesProcessed} pages)`
        )
    }

    /**
     * Audience cap reached. Emit the customer-facing log + metric, then
     * advance state to pendingTerminal='completed' with truncated_at_count
     * so the next execution writes the truncation to Django.
     */
    private async transitionToTruncatedTerminal(job: CyclotronV2DequeuedJob, state: BatchResolverState): Promise<void> {
        counterBatchHogFlowAudienceTruncated.labels({ hog_flow_id: state.hogFlowId }).inc()

        const message = `Audience exceeded the max cap of ${state.maxAudienceSize}, ${state.totalEnqueued} persons enqueued; the remainder did not receive this workflow.`
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

        const newState: BatchResolverState = {
            ...state,
            pendingTerminal: 'completed',
            truncatedAtCount: state.totalEnqueued,
        }
        await job.reschedule({ scheduledAt: new Date(), state: serializeResolverState(newState) })
    }

    /**
     * Hard failure path: a non-retryable problem (deleted team/workflow,
     * malformed filter). Flip into pendingTerminal='failed' so the next
     * execution writes the failed status to Django. Children already
     * enqueued continue executing normally.
     */
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
        }
        await job.reschedule({ scheduledAt: new Date(), state: serializeResolverState(newState) })
    }

    /**
     * Write terminal status to Django via the idempotent PUT endpoint.
     * Only acks the cyclotron job after Django acknowledges. On Django
     * failure, reschedules with backoff — same Django call will be replayed.
     */
    private async processTerminalWrite(job: CyclotronV2DequeuedJob, state: BatchResolverState): Promise<void> {
        if (!state.pendingTerminal) {
            // Invariant violation — pendingTerminal is the entry condition.
            await job.fail()
            return
        }

        try {
            await this.putBatchJobStatusFn(
                state.teamId,
                state.batchJobId,
                state.pendingTerminal,
                state.truncatedAtCount
            )
        } catch (err) {
            logger.warn('⚠️', `${this.name} - terminal status write failed, will retry`, {
                batchJobId: state.batchJobId,
                pendingTerminal: state.pendingTerminal,
                error: serializeError(err),
            })
            counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'terminal_write_failure' }).inc()
            await job.reschedule({ scheduledAt: new Date(Date.now() + RETRY_BACKOFF_MS) })
            return
        }

        // Flush any queued logs/metrics before acking.
        await this.hogFunctionMonitoringService.flush().catch((err) => {
            // Don't block ack on log flush — the resolver work itself succeeded.
            logger.warn('⚠️', 'Failed to flush monitoring after resolver ack', { error: serializeError(err) })
        })

        await job.ack()
        logger.info('✅', `${this.name} - batch ${state.batchJobId} → ${state.pendingTerminal}`, {
            totalEnqueued: state.totalEnqueued,
            truncatedAtCount: state.truncatedAtCount ?? null,
            pagesProcessed: state.pagesProcessed,
        })
    }

    /**
     * PUT the terminal status to Django. Endpoint is idempotent — if the row
     * is already in a terminal state, returns 200 no-op.
     */
    private async putBatchJobStatus(
        teamId: number,
        batchJobId: string,
        status: 'completed' | 'failed',
        truncatedAtCount: number | undefined
    ): Promise<void> {
        const urlPath = `/api/projects/${teamId}/internal/hog_flows/batch_jobs/${batchJobId}/status` as const
        const body: Record<string, unknown> = { status }
        if (truncatedAtCount !== undefined) {
            body.truncated_at_count = truncatedAtCount
        }

        const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
            urlPath,
            fetchParams: {
                method: 'PUT',
                body: JSON.stringify(body),
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

/**
 * Merge HogFlow's default variables with any per-run overrides. Per-run
 * overrides take precedence — the batch creator (UI/scheduler) can override
 * defaults via the variables field on HogFlowBatchJob.
 */
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

/**
 * Build a CyclotronJobInvocation for one person in a batch. Mirrors the
 * shape produced by the legacy Kafka consumer's createHogFlowInvocation so
 * children land in cyclotron_jobs looking the same regardless of whether
 * the trigger came through Kafka or the new resolver path.
 */
function buildHogFlowInvocation(params: {
    siteUrl: string
    parentRunId: string
    teamId: number
    hogFlowId: string
    personId: string
    defaultVariables: Record<string, unknown>
}): CyclotronJobInvocation {
    const invocationGlobals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
        team: { id: params.teamId } as any,
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
        } as any,
        teamId: params.teamId,
        functionId: params.hogFlowId,
        parentRunId: params.parentRunId,
        person: invocationGlobals.person as any,
        filterGlobals,
        queue: 'hogflow' as const,
        queuePriority: 1,
        queueScheduledAt: DateTime.now(),
    } as CyclotronJobInvocation
}
