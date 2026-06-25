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

const RETRY_BACKOFF_MS = 5_000

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

    private cyclotronWorker: CyclotronV2Worker
    private internalFetchService: InternalFetchService
    private hogFlowBatchPersonQueryService: HogFlowBatchPersonQueryService

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

    private async processResolverJob(job: CyclotronV2DequeuedJob): Promise<void> {
        let state: BatchResolverState
        try {
            state = deserializeResolverState(job.state)
        } catch (err) {
            // Schema drift, corrupted state, or a job from an incompatible
            // older deploy. None should happen in steady state — alert on
            // the counter so we notice fast.
            counterBatchHogFlowResolverPagesProcessed.labels({ outcome: 'invalid_state' }).inc()
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

        const newState: BatchResolverState = {
            ...state,
            cursor: page.cursor,
            totalEnqueued: state.totalEnqueued + children.length,
            pagesProcessed: state.pagesProcessed + 1,
        }
        if (!page.has_more) {
            newState.pendingTerminal = 'completed'
        }

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

// Mirrors `createHogFlowInvocation` from the legacy Kafka consumer so children
// land in cyclotron_jobs looking the same regardless of dispatch path.
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
