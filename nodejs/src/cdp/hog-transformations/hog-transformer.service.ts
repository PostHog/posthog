import { Counter, Gauge, Histogram } from 'prom-client'

import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PluginEvent } from '~/plugin-scaffold'

import { CyclotronJobInvocationResult, HogFunctionInvocationGlobals, HogFunctionType } from '../../cdp/types'
import { isLegacyPluginHogFunction } from '../../cdp/utils'
import { Hub } from '../../types'
import { GeoIPService, GeoIp } from '../../utils/geoip'
import { logger } from '../../utils/logger'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogInputsService } from '../services/hog-inputs.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { EmailService } from '../services/messaging/email.service'
import { RecipientTokensService } from '../services/messaging/recipient-tokens.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocation } from '../utils/invocation-utils'
import { getTransformationFunctions } from './transformation-functions'

export interface HogTransformerConfig {
    siteUrl: string
    hogWatcherSampleRate: number
}

export const hogTransformationDroppedEvents = new Counter({
    name: 'hog_transformation_dropped_events',
    help: 'Indicates how many events are dropped by hog transformations',
})

export const hogTransformationInvocations = new Counter({
    name: 'hog_transformation_invocations_total',
    help: 'Number of times transformEvent was called directly',
})

export const hogTransformationAttempts = new Counter({
    name: 'hog_transformation_attempts_total',
    help: 'Number of transformation attempts before any processing',
    labelNames: ['type'],
})

export const hogTransformationCompleted = new Counter({
    name: 'hog_transformation_completed_total',
    help: 'Number of successfully completed transformations',
    labelNames: ['type'],
})

export const hogWatcherLatency = new Histogram({
    name: 'hog_watcher_latency_seconds',
    help: 'Time spent in HogWatcher operations in seconds during ingestion',
    labelNames: ['operation'],
})

export const hogTransformationPendingInvocationResults = new Gauge({
    name: 'hog_transformation_pending_invocation_results',
    help: 'Number of invocation results accumulated and waiting to be processed. High values indicate memory accumulation.',
})

export interface TransformationResult {
    event: PluginEvent | null
    invocationResults: CyclotronJobInvocationResult[]
}

export class HogTransformerService {
    private cachedStates: Record<string, HogWatcherState> = {}
    private invocationResults: CyclotronJobInvocationResult[] = []
    private cachedGeoIp?: GeoIp
    private cachedTransformationFunctions?: ReturnType<typeof getTransformationFunctions>

    constructor(
        private hogFunctionManager: HogFunctionManagerService,
        private hogExecutor: HogExecutorService,
        private hogWatcher: HogWatcherService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService,
        private pluginExecutor: LegacyPluginExecutorService,
        private geoipService: GeoIPService,
        private redis: RedisV2,
        private config: HogTransformerConfig
    ) {}

    public async start(): Promise<void> {}

    public async stop(): Promise<void> {
        await this.processInvocationResults()
        await this.redis.useClient({ name: 'cleanup' }, async (client) => {
            await client.quit()
        })
    }

    public async processInvocationResults(): Promise<void> {
        const results = [...this.invocationResults]
        this.invocationResults = []
        hogTransformationPendingInvocationResults.set(0)

        const shouldRunHogWatcher = Math.random() < this.config.hogWatcherSampleRate

        await Promise.allSettled([
            this.hogFunctionMonitoringService
                .queueInvocationResults(results)
                .then(() => this.hogFunctionMonitoringService.flush()),

            shouldRunHogWatcher
                ? this.hogWatcher.observeResults(results).catch((error) => {
                      logger.warn('⚠️', 'HogWatcher observeResults failed', { error })
                  })
                : Promise.resolve(),
        ])
    }

    private async getTransformationFunctions() {
        if (!this.cachedTransformationFunctions) {
            this.cachedGeoIp = await this.geoipService.get()
            this.cachedTransformationFunctions = getTransformationFunctions(this.cachedGeoIp)
        }
        return this.cachedTransformationFunctions
    }

    private createInvocationGlobals(event: PluginEvent): HogFunctionInvocationGlobals {
        return {
            project: {
                id: event.team_id,
                name: '',
                url: this.config.siteUrl,
            },
            event: {
                uuid: event.uuid,
                event: event.event,
                distinct_id: event.distinct_id,
                properties: event.properties || {},
                elements_chain: event.properties?.elements_chain || '',
                timestamp: event.timestamp || '',
                url: event.properties?.$current_url || '',
            },
        }
    }

    private async transformEventAndProduceMessagesImpl(event: PluginEvent): Promise<TransformationResult> {
        hogTransformationAttempts.inc({ type: 'with_messages' })

        const teamHogFunctions = await this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, ['transformation'])

        const transformationResult = await this.transformEvent(event, teamHogFunctions)

        for (const result of transformationResult.invocationResults) {
            this.invocationResults.push(result)
        }
        hogTransformationPendingInvocationResults.set(this.invocationResults.length)

        hogTransformationCompleted.inc({ type: 'with_messages' })
        return {
            ...transformationResult,
        }
    }

    public transformEventAndProduceMessages(event: PluginEvent): Promise<TransformationResult> {
        return instrumentFn(`hogTransformer.transformEventAndProduceMessages`, () =>
            this.transformEventAndProduceMessagesImpl(event)
        )
    }

    private async transformEventImpl(
        event: PluginEvent,
        teamHogFunctions: HogFunctionType[]
    ): Promise<TransformationResult> {
        hogTransformationInvocations.inc()

        // Early return if no transformations to run
        if (teamHogFunctions.length === 0) {
            return {
                event,
                invocationResults: [],
            }
        }

        const results: CyclotronJobInvocationResult[] = []
        const transformationsSucceeded: string[] = []
        const transformationsFailed: string[] = []
        const transformationsSkipped: string[] = []

        const shouldRunHogWatcher = Math.random() < this.config.hogWatcherSampleRate

        // Create globals once and update the event properties after each transformation
        const globals = this.createInvocationGlobals(event)

        for (const hogFunction of teamHogFunctions) {
            // Check if function is in a degraded state, but only if hogwatcher is enabled
            if (shouldRunHogWatcher) {
                const functionState = this.cachedStates[hogFunction.id]

                // If the function is in a degraded state, skip it
                if (functionState && functionState === HogWatcherState.disabled) {
                    this.hogFunctionMonitoringService.queueAppMetric(
                        {
                            team_id: event.team_id,
                            app_source_id: hogFunction.id,
                            metric_kind: 'failure',
                            metric_name: 'disabled_permanently',
                            count: 1,
                        },
                        'hog_function'
                    )
                    continue
                }
            }

            // Create identifier after the disabled check passes to avoid string allocation for skipped functions
            const transformationIdentifier = `${hogFunction.name} (${hogFunction.id})`

            // Create filterGlobals for each iteration - it references globals.event.properties
            // which gets updated after each successful transformation
            const filterGlobals = convertToHogFunctionFilterGlobal(globals)

            // Check if function has filters - if not, always apply
            if (hogFunction.filters?.bytecode) {
                const filterResults = await filterFunctionInstrumented({
                    fn: hogFunction,
                    filters: hogFunction.filters,
                    filterGlobals,
                })

                // If filter didn't pass skip the actual transformation and add logs and errors from the filterResult
                this.hogFunctionMonitoringService.queueAppMetrics(filterResults.metrics, 'hog_function')
                this.hogFunctionMonitoringService.queueLogs(filterResults.logs, 'hog_function')

                if (!filterResults.match) {
                    transformationsSkipped.push(transformationIdentifier)
                    continue
                }
            }

            const result = await this.executeHogFunction(hogFunction, globals)

            results.push(result)

            if (result.error) {
                transformationsFailed.push(transformationIdentifier)
                continue
            }

            if (!result.execResult) {
                hogTransformationDroppedEvents.inc()
                this.hogFunctionMonitoringService.queueAppMetric(
                    {
                        team_id: event.team_id,
                        app_source_id: hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'dropped',
                        count: 1,
                    },
                    'hog_function'
                )
                transformationsFailed.push(transformationIdentifier)
                return {
                    event: null,
                    invocationResults: results,
                }
            }

            const transformedEvent: unknown = result.execResult

            if (
                !transformedEvent ||
                typeof transformedEvent !== 'object' ||
                !('properties' in transformedEvent) ||
                !transformedEvent.properties ||
                typeof transformedEvent.properties !== 'object'
            ) {
                logger.error('⚠️', 'Invalid transformation result - missing or invalid properties', {
                    function_id: hogFunction.id,
                })
                transformationsFailed.push(transformationIdentifier)
                continue
            }

            event.properties = transformedEvent.properties as Record<string, any>
            event.ip = event.properties.$ip ?? null

            if ('event' in transformedEvent) {
                if (typeof transformedEvent.event !== 'string') {
                    logger.error('⚠️', 'Invalid transformation result - event name must be a string', {
                        function_id: hogFunction.id,
                        event: transformedEvent.event,
                    })
                    transformationsFailed.push(transformationIdentifier)
                    continue
                }
                event.event = transformedEvent.event
            }

            if ('distinct_id' in transformedEvent) {
                if (typeof transformedEvent.distinct_id !== 'string') {
                    logger.error('⚠️', 'Invalid transformation result - distinct_id must be a string', {
                        function_id: hogFunction.id,
                        distinct_id: transformedEvent.distinct_id,
                    })
                    transformationsFailed.push(transformationIdentifier)
                    continue
                }
                event.distinct_id = transformedEvent.distinct_id
            }

            // Update globals so the next transformation sees the changes
            globals.event.properties = event.properties
            globals.event.event = event.event
            globals.event.distinct_id = event.distinct_id

            transformationsSucceeded.push(transformationIdentifier)
        }

        // Use direct property assignment instead of spreading to avoid copying the entire object
        if (
            transformationsFailed.length > 0 ||
            transformationsSkipped.length > 0 ||
            transformationsSucceeded.length > 0
        ) {
            event.properties = event.properties || {}
            if (transformationsFailed.length > 0) {
                event.properties.$transformations_failed = transformationsFailed
            }
            if (transformationsSkipped.length > 0) {
                event.properties.$transformations_skipped = transformationsSkipped
            }
            if (transformationsSucceeded.length > 0) {
                event.properties.$transformations_succeeded = transformationsSucceeded
            }
        }

        return {
            event,
            invocationResults: results,
        }
    }

    public transformEvent(event: PluginEvent, teamHogFunctions: HogFunctionType[]): Promise<TransformationResult> {
        // Sanitize transform event properties
        if (event.properties) {
            for (const key of ['$transformations_failed', '$transformations_skipped', '$transformations_succeeded']) {
                if (key in event.properties) {
                    delete event.properties[key]
                }
            }
        }

        return instrumentFn(`hogTransformer.transformEvent`, () => this.transformEventImpl(event, teamHogFunctions))
    }

    private async executeHogFunction(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<CyclotronJobInvocationResult> {
        const transformationFunctions = await this.getTransformationFunctions()
        const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)

        const invocation = createInvocation(globalsWithInputs, hogFunction)

        const result = isLegacyPluginHogFunction(hogFunction)
            ? await this.pluginExecutor.execute(invocation)
            : await this.hogExecutor.execute(invocation, {
                  functions: transformationFunctions,
                  asyncFunctionsNames: [],
              })
        return result
    }

    public async fetchAndCacheHogFunctionStates(functionIds: string[]): Promise<void> {
        const timer = hogWatcherLatency.startTimer({ operation: 'getStates' })
        const states = await this.hogWatcher.getEffectiveStates(functionIds)
        timer()

        // Save only the state enum value to cache
        Object.entries(states).forEach(([id, state]) => {
            this.cachedStates[id] = state.state
        })
    }

    public clearHogFunctionStates(functionIds?: string[]): void {
        if (functionIds) {
            // Clear specific function states
            functionIds.forEach((id) => {
                delete this.cachedStates[id]
            })
        } else {
            // Clear all states if no IDs provided
            this.cachedStates = {}
        }
    }
}

/**
 * Hub fields needed by createHogTransformerService factory.
 * This will be removed once callers are themselves migrated off Hub.
 */
export type HogTransformerServiceDeps = Pick<
    Hub,
    | 'CDP_HOG_WATCHER_SAMPLE_RATE'
    | 'geoipService'
    | 'SITE_URL'
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'CDP_REDIS_HOST'
    | 'CDP_REDIS_PORT'
    | 'CDP_REDIS_PASSWORD'
    | 'postgres'
    | 'pubSub'
    | 'encryptedFields'
    | 'CDP_WATCHER_HOG_COST_TIMING_UPPER_MS'
    | 'CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN'
    | 'CDP_FETCH_BACKOFF_BASE_MS'
    | 'CDP_FETCH_BACKOFF_MAX_MS'
    | 'CDP_FETCH_RETRIES'
    | 'integrationManager'
    | 'ENCRYPTION_SALT_KEYS'
    | 'SES_ACCESS_KEY_ID'
    | 'SES_SECRET_ACCESS_KEY'
    | 'SES_REGION'
    | 'SES_ENDPOINT'
    | 'kafkaProducer'
    | 'teamManager'
    | 'internalCaptureService'
    | 'HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC'
    | 'HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC'
    | 'CDP_WATCHER_HOG_COST_TIMING_LOWER_MS'
    | 'CDP_WATCHER_HOG_COST_TIMING'
    | 'CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS'
    | 'CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS'
    | 'CDP_WATCHER_ASYNC_COST_TIMING'
    | 'CDP_WATCHER_SEND_EVENTS'
    | 'CDP_WATCHER_BUCKET_SIZE'
    | 'CDP_WATCHER_REFILL_RATE'
    | 'CDP_WATCHER_TTL'
    | 'CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS'
    | 'CDP_WATCHER_THRESHOLD_DEGRADED'
    | 'CDP_WATCHER_STATE_LOCK_TTL'
    | 'CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS'
    | 'CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS'
>

export function createHogTransformerService(hub: HogTransformerServiceDeps): HogTransformerService {
    const redis = createRedisV2PoolFromConfig({
        connection: hub.CDP_REDIS_HOST
            ? {
                  url: hub.CDP_REDIS_HOST,
                  options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  name: 'hog-transformer-redis',
              }
            : { url: hub.REDIS_URL, name: 'hog-transformer-redis-fallback' },
        poolMinSize: hub.REDIS_POOL_MIN_SIZE,
        poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
    })
    const hogFunctionManager = new HogFunctionManagerService(hub.postgres, hub.pubSub, hub.encryptedFields)
    const hogInputsService = new HogInputsService(hub.integrationManager, hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
    const emailService = new EmailService(
        {
            sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
            sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
            sesRegion: hub.SES_REGION,
            sesEndpoint: hub.SES_ENDPOINT,
        },
        hub.integrationManager,
        hub.ENCRYPTION_SALT_KEYS,
        hub.SITE_URL
    )
    const recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
    const hogExecutor = new HogExecutorService(
        {
            hogCostTimingUpperMs: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
            googleAdwordsDeveloperToken: hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN,
            fetchRetries: hub.CDP_FETCH_RETRIES,
            fetchBackoffBaseMs: hub.CDP_FETCH_BACKOFF_BASE_MS,
            fetchBackoffMaxMs: hub.CDP_FETCH_BACKOFF_MAX_MS,
        },
        { teamManager: hub.teamManager, siteUrl: hub.SITE_URL },
        hogInputsService,
        emailService,
        recipientTokensService
    )
    const pluginExecutor = new LegacyPluginExecutorService(hub.postgres, hub.geoipService)
    const hogFunctionMonitoringService = new HogFunctionMonitoringService(
        hub.kafkaProducer,
        hub.internalCaptureService,
        hub.teamManager,
        hub.HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC,
        hub.HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC
    )
    const hogWatcher = new HogWatcherService(
        hub.teamManager,
        {
            hogCostTimingLowerMs: hub.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS,
            hogCostTimingUpperMs: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
            hogCostTiming: hub.CDP_WATCHER_HOG_COST_TIMING,
            asyncCostTimingLowerMs: hub.CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS,
            asyncCostTimingUpperMs: hub.CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS,
            asyncCostTiming: hub.CDP_WATCHER_ASYNC_COST_TIMING,
            sendEvents: hub.CDP_WATCHER_SEND_EVENTS,
            bucketSize: hub.CDP_WATCHER_BUCKET_SIZE,
            refillRate: hub.CDP_WATCHER_REFILL_RATE,
            ttl: hub.CDP_WATCHER_TTL,
            automaticallyDisableFunctions: hub.CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS,
            thresholdDegraded: hub.CDP_WATCHER_THRESHOLD_DEGRADED,
            stateLockTtl: hub.CDP_WATCHER_STATE_LOCK_TTL,
            observeResultsBufferTimeMs: hub.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS,
            observeResultsBufferMaxResults: hub.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS,
        },
        redis
    )

    return new HogTransformerService(
        hogFunctionManager,
        hogExecutor,
        hogWatcher,
        hogFunctionMonitoringService,
        pluginExecutor,
        hub.geoipService,
        redis,
        {
            siteUrl: hub.SITE_URL,
            hogWatcherSampleRate: hub.CDP_HOG_WATCHER_SAMPLE_RATE,
        }
    )
}
