import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { RedisV2 } from '../../common/redis/redis-v2'
import { KeyedRateLimitRequest, KeyedRateLimiterService } from '../../common/services/keyed-rate-limiter.service'
import { QuotaLimiting } from '../../common/services/quota-limiting.service'
import { CdpValkeyShadowPools } from '../cdp-services'
import { counterRateLimited } from '../consumers/metrics'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals, LogEntry, MinimalAppMetric } from '../types'
import { mirrorCall } from '../utils/mirror-call'
import { HogFlowExecutorService } from './hogflows/hogflow-executor.service'
import { HogFlowManagerService } from './hogflows/hogflow-manager.service'
import { shouldBlockHogFlowDueToQuota } from './hogflows/hogflow-quota-limiting'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogMaskerService } from './monitoring/hog-masker.service'
import { HogWatcherService, HogWatcherState } from './monitoring/hog-watcher.service'

export interface HogFlowInvocationPipelineConfig {
    CDP_RATE_LIMITER_BUCKET_SIZE: number
    CDP_RATE_LIMITER_REFILL_RATE: number
    CDP_RATE_LIMITER_TTL: number
}

export interface HogFlowInvocationPipelineDeps {
    hogFlowManager: HogFlowManagerService
    hogFlowExecutor: HogFlowExecutorService
    hogWatcher: HogWatcherService
    hogWatcherMirror: HogWatcherService | null
    hogMasker: HogMaskerService
    hogFunctionMonitoringService: HogFunctionMonitoringService
    quotaLimiting: QuotaLimiting
    redis: RedisV2
    valkeyShadow: CdpValkeyShadowPools | null
}

/**
 * Encapsulates the pipeline that turns event globals into hog flow invocations:
 * load hogflows → execute filters → watcher state → rate limit → quota → masking → metrics.
 *
 * Consumers compose this service rather than inheriting it.
 */
export class HogFlowInvocationPipeline {
    private hogRateLimiter: KeyedRateLimiterService
    private hogRateLimiterMirror: KeyedRateLimiterService | null

    constructor(
        private config: HogFlowInvocationPipelineConfig,
        private deps: HogFlowInvocationPipelineDeps
    ) {
        const rateLimiterConfig = {
            name: 'hog-rate-limiter',
            bucketSize: config.CDP_RATE_LIMITER_BUCKET_SIZE,
            refillRate: config.CDP_RATE_LIMITER_REFILL_RATE,
            ttlSeconds: config.CDP_RATE_LIMITER_TTL,
        }
        this.hogRateLimiter = new KeyedRateLimiterService(rateLimiterConfig, deps.redis)
        this.hogRateLimiterMirror = deps.valkeyShadow
            ? new KeyedRateLimiterService(rateLimiterConfig, deps.valkeyShadow.writer)
            : null
    }

    @instrumented('cdpConsumer.handleEachBatch.queueMatchingFlows')
    public async buildInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[],
        options?: {
            // Predicate evaluated per (flow, globals) before the executor runs filter bytecode.
            // The consumer is the natural layer to decide trigger-source compatibility because it
            // knows its own source (events consumer → event triggers; DWH consumer → matching
            // warehouse-table triggers). Flows that fail the predicate are skipped without
            // touching the executor.
            eligibilityFn?: (hogFlow: HogFlow, globals: HogFunctionInvocationGlobals) => boolean
        }
    ): Promise<CyclotronJobInvocation[]> {
        const teamsToLoad = [...new Set(invocationGlobals.map((x) => x.project.id))]
        const hogFlowsByTeam = await this.deps.hogFlowManager.getHogFlowsForTeams(teamsToLoad)
        const eligibilityFn = options?.eligibilityFn

        const possibleInvocations = (
            await Promise.all(
                invocationGlobals.map(async (globals) => {
                    const teamHogFlows = hogFlowsByTeam[globals.project.id]
                    const eligibleFlows = eligibilityFn
                        ? teamHogFlows.filter((flow) => eligibilityFn(flow, globals))
                        : teamHogFlows

                    const { invocations, metrics, logs } = await this.deps.hogFlowExecutor.buildHogFlowInvocations(
                        eligibleFlows,
                        globals
                    )

                    this.deps.hogFunctionMonitoringService.queueAppMetrics(metrics, 'hog_flow')
                    this.deps.hogFunctionMonitoringService.queueLogs(logs, 'hog_flow')

                    return invocations
                })
            )
        ).flat()

        const hogFlowIds = possibleInvocations.map((x) => x.hogFlow.id)
        const [states] = await Promise.all([
            instrumentFn('cdpConsumer.handleEachBatch.hogWatcher.getEffectiveStates', async () => {
                return await this.deps.hogWatcher.getEffectiveStates(hogFlowIds)
            }),
            mirrorCall('hog-watcher.getEffectiveStates', () =>
                this.deps.hogWatcherMirror?.getEffectiveStates(hogFlowIds)
            ),
        ])

        const rateLimitInputs: KeyedRateLimitRequest[] = possibleInvocations.map((x) => ({
            id: x.hogFlow.id,
            cost: 1,
        }))
        const [rateLimits] = await Promise.all([
            instrumentFn('cdpConsumer.handleEachBatch.hogRateLimiter.rateLimitGrouped', async () => {
                return await this.hogRateLimiter.rateLimitGrouped(rateLimitInputs)
            }),
            mirrorCall('hog-rate-limiter.rateLimitGrouped', () =>
                this.hogRateLimiterMirror?.rateLimitGrouped(rateLimitInputs)
            ),
        ])
        const validInvocations: CyclotronJobInvocation[] = []

        await Promise.all(
            possibleInvocations.map(async (item, index) => {
                try {
                    const rateLimit = rateLimits[index][1]
                    if (rateLimit.isRateLimited) {
                        counterRateLimited.labels({ kind: 'hog_flow', function_id: item.functionId }).inc()
                        this.deps.hogFunctionMonitoringService.queueAppMetric(
                            {
                                team_id: item.teamId,
                                app_source_id: item.functionId,
                                metric_kind: 'failure',
                                metric_name: 'rate_limited',
                                count: 1,
                            },
                            'hog_flow'
                        )

                        const eventUuid = item.state?.event?.uuid
                        const personId = item.person?.id

                        const logEntry: LogEntry = {
                            timestamp: DateTime.now(),
                            level: 'warn',
                            message: `Workflow invocation dropped due to rate limiting for [Person:${personId ?? 'unknown'}] on [Event:${eventUuid ?? 'unknown'}]`,
                            team_id: item.teamId,
                            log_source: 'hog_flow',
                            log_source_id: item.functionId,
                            instance_id: item.id,
                        }
                        this.deps.hogFunctionMonitoringService.queueLogs([logEntry], 'hog_flow')

                        logger.warn('⚠️', 'Hogflow invocation rate limited', {
                            teamId: item.teamId,
                            hogFlowId: item.functionId,
                            hogFlowName: item.hogFlow.name,
                            eventUuid,
                            personId,
                        })

                        return
                    }
                } catch (e) {
                    captureException(e)
                    logger.error('🔴', 'Error checking rate limit for hog flow', { err: e })
                }

                // Check quota limits for workflow actions
                const isQuotaLimited = await shouldBlockHogFlowDueToQuota(item, {
                    quotaLimiting: this.deps.quotaLimiting,
                    hogFunctionMonitoringService: this.deps.hogFunctionMonitoringService,
                })

                if (isQuotaLimited) {
                    return
                }

                const state = states[item.hogFlow.id].state
                if (state === HogWatcherState.disabled) {
                    this.deps.hogFunctionMonitoringService.queueAppMetric(
                        {
                            team_id: item.teamId,
                            app_source_id: item.functionId,
                            metric_kind: 'failure',
                            metric_name: 'disabled_permanently',
                            count: 1,
                        },
                        'hog_flow'
                    )
                    return
                }

                if (state === HogWatcherState.degraded) {
                    item.queuePriority = 2
                }

                validInvocations.push(item)
            })
        )

        const { masked, notMasked: notMaskedInvocations } = await this.deps.hogMasker.filterByMasking(validInvocations)

        this.deps.hogFunctionMonitoringService.queueAppMetrics(
            masked.map((item) => ({
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'other',
                metric_name: 'masked',
                count: 1,
            })),
            'hog_flow'
        )

        const triggeredInvocationsMetrics: MinimalAppMetric[] = []

        notMaskedInvocations.forEach((item) => {
            triggeredInvocationsMetrics.push({
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'other',
                metric_name: 'triggered',
                count: 1,
            })
        })

        this.deps.hogFunctionMonitoringService.queueAppMetrics(triggeredInvocationsMetrics, 'hog_flow')

        return notMaskedInvocations
    }
}
