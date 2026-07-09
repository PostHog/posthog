import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { RedisV2 } from '../../common/redis/redis-v2'
import { KeyedRateLimitRequest, KeyedRateLimiterService } from '../../common/services/keyed-rate-limiter.service'
import { QuotaLimiting } from '../../common/services/quota-limiting.service'
import { CdpValkeyShadowPools } from '../cdp-services'
import { counterHogFunctionStateOnEvent, counterRateLimited } from '../consumers/metrics'
import { shouldBlockInvocationDueToQuota } from '../consumers/quota-limiting-helper'
import {
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    HogFunctionTypeType,
    MinimalAppMetric,
} from '../types'
import { mirrorCall } from '../utils/mirror-call'
import { HogExecutorService } from './hog-executor.service'
import { HogFunctionManagerService } from './managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogMaskerService } from './monitoring/hog-masker.service'
import { HogWatcherService, HogWatcherState } from './monitoring/hog-watcher.service'
import { RustVmFilterShadow } from './rust-vm-filter-shadow'

export interface HogFunctionInvocationPipelineConfig {
    CDP_RATE_LIMITER_BUCKET_SIZE: number
    CDP_RATE_LIMITER_REFILL_RATE: number
    CDP_RATE_LIMITER_TTL: number
    CDP_OVERFLOW_QUEUE_ENABLED: boolean
    CDP_HOG_RUST_VM_SHADOW_FILTER_SAMPLE_RATE: number
    MMDB_FILE_LOCATION: string
}

export interface HogFunctionInvocationPipelineDeps {
    hogFunctionManager: HogFunctionManagerService
    hogExecutor: HogExecutorService
    hogWatcher: HogWatcherService
    hogWatcherMirror: HogWatcherService | null
    hogMasker: HogMaskerService
    hogFunctionMonitoringService: HogFunctionMonitoringService
    quotaLimiting: QuotaLimiting
    redis: RedisV2
    valkeyShadow: CdpValkeyShadowPools | null
}

export interface BuildHogFunctionInvocationsOptions {
    hogTypes: HogFunctionTypeType[]
    filterFn: (fn: HogFunctionType) => boolean
}

/**
 * Encapsulates the pipeline that turns event globals into hog function invocations:
 * load functions → execute filters → watcher state → rate limit → quota → masking → metrics.
 *
 * Consumers compose this service rather than inheriting it.
 */
export class HogFunctionInvocationPipeline {
    private hogRateLimiter: KeyedRateLimiterService
    private hogRateLimiterMirror: KeyedRateLimiterService | null
    private rustVmFilterShadow: RustVmFilterShadow

    constructor(
        private config: HogFunctionInvocationPipelineConfig,
        private deps: HogFunctionInvocationPipelineDeps
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
        this.rustVmFilterShadow = new RustVmFilterShadow({
            sampleRate: config.CDP_HOG_RUST_VM_SHADOW_FILTER_SAMPLE_RATE,
            mmdbPath: config.MMDB_FILE_LOCATION,
        })
    }

    @instrumented('cdpConsumer.handleEachBatch.queueMatchingFunctions')
    public async buildInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[],
        opts: BuildHogFunctionInvocationsOptions
    ): Promise<CyclotronJobInvocationHogFunction[]> {
        const teamsToLoad = [...new Set(invocationGlobals.map((x) => x.project.id))]
        const hogFunctionsByTeam = await this.deps.hogFunctionManager.getHogFunctionsForTeams(
            teamsToLoad,
            opts.hogTypes,
            opts.filterFn
        )

        const possibleInvocations = (
            await Promise.all(
                invocationGlobals.map(async (globals) => {
                    const teamHogFunctions = hogFunctionsByTeam[globals.project.id]

                    const { invocations, metrics, logs } = await this.deps.hogExecutor.buildHogFunctionInvocations(
                        teamHogFunctions,
                        globals,
                        this.rustVmFilterShadow
                    )

                    this.deps.hogFunctionMonitoringService.queueAppMetrics(metrics, 'hog_function')
                    this.deps.hogFunctionMonitoringService.queueLogs(logs, 'hog_function')

                    return invocations
                })
            )
        ).flat()

        const hogFunctionIds = possibleInvocations.map((x) => x.hogFunction.id)
        const [states] = await Promise.all([
            instrumentFn('cdpConsumer.handleEachBatch.hogWatcher.getEffectiveStates', async () => {
                return await this.deps.hogWatcher.getEffectiveStates(hogFunctionIds)
            }),
            mirrorCall('hog-watcher.getEffectiveStates', () =>
                this.deps.hogWatcherMirror?.getEffectiveStates(hogFunctionIds)
            ),
        ])

        const rateLimitInputs: KeyedRateLimitRequest[] = possibleInvocations.map((x) => ({
            id: x.hogFunction.id,
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

        const validInvocations: CyclotronJobInvocationHogFunction[] = []

        await Promise.all(
            possibleInvocations.map(async (item, index) => {
                try {
                    const rateLimit = rateLimits[index][1]
                    if (rateLimit.isRateLimited) {
                        counterRateLimited.labels({ kind: 'hog_function', function_id: item.functionId }).inc()
                        // NOTE: We don't return here as we are just monitoring this feature currently
                    }
                } catch (e) {
                    captureException(e)
                    logger.error('🔴', 'Error checking rate limit for hog function', { err: e })
                }

                const isQuotaLimited = await shouldBlockInvocationDueToQuota(item, {
                    quotaLimiting: this.deps.quotaLimiting,
                    hogFunctionMonitoringService: this.deps.hogFunctionMonitoringService,
                })

                if (isQuotaLimited) {
                    return
                }

                const state = states[item.hogFunction.id].state

                counterHogFunctionStateOnEvent
                    .labels({
                        state: HogWatcherState[state],
                        kind: item.hogFunction.type,
                    })
                    .inc()

                if (state === HogWatcherState.disabled) {
                    this.deps.hogFunctionMonitoringService.queueAppMetric(
                        {
                            team_id: item.teamId,
                            app_source_id: item.functionId,
                            metric_kind: 'failure',
                            metric_name: 'disabled_permanently',
                            count: 1,
                        },
                        'hog_function'
                    )
                    return
                }

                if (state === HogWatcherState.degraded) {
                    item.queuePriority = 2
                    if (this.config.CDP_OVERFLOW_QUEUE_ENABLED) {
                        item.queue = 'hogoverflow'
                    }
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
            'hog_function'
        )

        const triggeredInvocationsMetrics: MinimalAppMetric[] = []

        // Track unique events that have been billed (billing is per-event, not per-destination)
        const billedEventUuids = new Set<string>()

        notMaskedInvocations.forEach((item) => {
            triggeredInvocationsMetrics.push({
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'other',
                metric_name: 'triggered',
                count: 1,
            })

            // Bill once per triggering event, not per destination
            if (item.hogFunction.type === 'destination') {
                const eventUuid = item.state?.globals?.event?.uuid
                if (eventUuid && !billedEventUuids.has(eventUuid)) {
                    billedEventUuids.add(eventUuid)
                    triggeredInvocationsMetrics.push({
                        team_id: item.teamId,
                        app_source_id: '_event_trigger',
                        instance_id: eventUuid,
                        metric_kind: 'billing',
                        metric_name: 'billable_invocation',
                        count: 1,
                    })
                }
            }
        })

        this.deps.hogFunctionMonitoringService.queueAppMetrics(triggeredInvocationsMetrics, 'hog_function')

        // Off the hot path: shadow-execute this batch's sampled filters on the Rust HogVM and
        // compare. Fire-and-forget via mirrorCall so it can never throw into or delay the primary
        // pipeline; the shadow guards against overlapping flushes internally.
        void mirrorCall('hogvm.rust-filter-shadow-flush', () => this.rustVmFilterShadow.flush(), 5000)

        return notMaskedInvocations
    }
}
