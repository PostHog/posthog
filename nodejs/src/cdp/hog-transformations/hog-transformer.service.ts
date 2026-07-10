import { Counter, Gauge, Histogram } from 'prom-client'

import { HogTransformationResult, HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { GeoIPService, GeoIp } from '~/common/utils/geoip'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManager } from '~/common/utils/team-manager'
import { PluginEvent } from '~/plugin-scaffold'

import { CyclotronJobInvocationResult, HogFunctionInvocationGlobals, HogFunctionType } from '../../cdp/types'
import { isLegacyPluginHogFunction } from '../../cdp/utils'
import type { CommonConfig } from '../../common/config'
import { CdpCoreServicesConfig, createCdpReaderRedisPool, createCdpValkeyShadowPools } from '../cdp-services'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogInputsService } from '../services/hog-inputs.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { IntegrationManagerService } from '../services/managers/integration-manager.service'
import { TeamWorkflowsConfigService } from '../services/managers/team-workflows-config.service'
import { EmailService } from '../services/messaging/email.service'
import { EmailTrackingCodeSigner } from '../services/messaging/helpers/tracking-code'
import { RecipientTokensService } from '../services/messaging/recipient-tokens.service'
import { HogFunctionMonitoringService, MonitoringOutput } from '../services/monitoring/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { EncryptedFields } from '../utils/encryption-utils'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocation } from '../utils/invocation-utils'
import { mirrorCall } from '../utils/mirror-call'
import { RustVmShadow } from './rust-vm-shadow'
import { getTransformationFunctions } from './transformation-functions'

export interface HogTransformerConfig {
    siteUrl: string
    hogWatcherSampleRate: number
    hogRustVmShadowSampleRate: number
    mmdbFileLocation: string
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

export const hogTransformationUnexpectedErrors = new Counter({
    name: 'hog_transformation_unexpected_errors_total',
    help: 'Number of unexpected errors during transformation execution. Any occurrence should trigger an alert as the transformation is skipped.',
})

export interface TransformationResult extends HogTransformationResult {
    event: PluginEvent | null
    invocationResults: CyclotronJobInvocationResult[]
}

export class HogTransformerService implements HogTransformer {
    private cachedStates: Record<string, HogWatcherState> = {}
    private invocationResults: CyclotronJobInvocationResult[] = []
    private cachedGeoIp?: GeoIp
    private cachedTransformationFunctions?: ReturnType<typeof getTransformationFunctions>
    private rustVmShadow: RustVmShadow

    constructor(
        private hogFunctionManager: HogFunctionManagerService,
        private hogExecutor: HogExecutorService,
        private hogWatcher: HogWatcherService,
        private hogWatcherMirror: HogWatcherService | null,
        private hogFunctionMonitoringService: HogFunctionMonitoringService,
        private pluginExecutor: LegacyPluginExecutorService,
        private geoipService: GeoIPService,
        private redis: RedisV2,
        private config: HogTransformerConfig
    ) {
        this.rustVmShadow = new RustVmShadow({
            sampleRate: config.hogRustVmShadowSampleRate,
            mmdbPath: config.mmdbFileLocation,
        })
    }

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

        this.hogFunctionMonitoringService.queueInvocationResults(results)

        await Promise.allSettled([
            this.hogFunctionMonitoringService.flush(),

            shouldRunHogWatcher
                ? this.hogWatcher.observeResults(results).catch((error) => {
                      logger.warn('⚠️', 'HogWatcher observeResults failed', { error })
                  })
                : Promise.resolve(),

            shouldRunHogWatcher
                ? mirrorCall('hog-watcher.observeResults', () => this.hogWatcherMirror?.observeResults(results))
                : Promise.resolve(),

            mirrorCall('hogvm.rust-shadow-flush', () => this.rustVmShadow.flush(), 5000),
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
                elements_chain: event.properties?.$elements_chain || '',
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

            let result: CyclotronJobInvocationResult
            try {
                result = await this.executeHogFunction(hogFunction, globals)
            } catch (err) {
                hogTransformationUnexpectedErrors.inc()
                logger.error('⚠️', 'Unexpected error executing transformation', {
                    function_id: hogFunction.id,
                    team_id: event.team_id,
                    error: String(err),
                })
                this.hogFunctionMonitoringService.queueAppMetric(
                    {
                        team_id: event.team_id,
                        app_source_id: hogFunction.id,
                        metric_kind: 'failure',
                        metric_name: 'failed',
                        count: 1,
                    },
                    'hog_function'
                )
                transformationsFailed.push(transformationIdentifier)
                continue
            }

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
                    droppedBy: { id: hogFunction.id, name: hogFunction.name },
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

        if (isLegacyPluginHogFunction(hogFunction)) {
            return await this.pluginExecutor.execute(invocation)
        }

        // Snapshot before execution: later transformations in the chain mutate these globals.
        const shadowGlobalsJson = this.rustVmShadow.shouldCapture() ? JSON.stringify(globalsWithInputs) : null

        const result = await this.hogExecutor.execute(invocation, {
            functions: transformationFunctions,
            asyncFunctionsNames: [],
        })

        if (shadowGlobalsJson) {
            this.rustVmShadow.capture({
                functionId: hogFunction.id,
                teamId: hogFunction.team_id,
                bytecode: hogFunction.bytecode,
                globalsJson: shadowGlobalsJson,
                node: {
                    finished: result.finished,
                    error: result.error != null ? String(result.error) : undefined,
                    // Snapshot: the transformer mutates execResult right after this returns.
                    execResultJson: result.execResult !== undefined ? JSON.stringify(result.execResult) : null,
                    durationMs: result.invocation.state.timings
                        .filter((timing) => timing.kind === 'hog')
                        .reduce((sum, timing) => sum + timing.duration_ms, 0),
                },
            })
        }

        return result
    }

    public async fetchAndCacheHogFunctionStates(functionIds: string[]): Promise<void> {
        const timer = hogWatcherLatency.startTimer({ operation: 'getStates' })
        const [states] = await Promise.all([
            this.hogWatcher.getEffectiveStates(functionIds),
            mirrorCall('hog-watcher.getEffectiveStates', () => this.hogWatcherMirror?.getEffectiveStates(functionIds)),
        ])
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

    public async prefetchTransformationStatesForTeams(teamIds: number[]): Promise<void> {
        this.clearHogFunctionStates()
        if (teamIds.length === 0) {
            return
        }
        const teamHogFunctionIds = await this.hogFunctionManager.getHogFunctionIdsForTeams(teamIds, ['transformation'])
        const allHogFunctionIds = Object.values(teamHogFunctionIds).flat()
        if (allHogFunctionIds.length > 0) {
            await this.fetchAndCacheHogFunctionStates(allHogFunctionIds)
        }
    }
}

/**
 * Config needed by the HogTransformer when running inside ingestion.
 * This is CdpCoreServicesConfig (CDP redis, watcher, monitoring, encryption, etc.)
 * plus the ingestion-specific sample rates from CommonConfig.
 */
export type HogTransformerServiceConfig = CdpCoreServicesConfig &
    Pick<CommonConfig, 'CDP_HOG_WATCHER_SAMPLE_RATE' | 'CDP_HOG_RUST_VM_SHADOW_SAMPLE_RATE' | 'MMDB_FILE_LOCATION'>

export interface HogTransformerServiceDeps {
    geoipService: GeoIPService
    postgres: PostgresRouter
    pubSub: PubSub
    encryptedFields: EncryptedFields
    integrationManager: IntegrationManagerService
    monitoringOutputs: IngestionOutputs<MonitoringOutput>
    teamManager: TeamManager
}

export function createHogTransformerService(
    config: HogTransformerServiceConfig,
    deps: HogTransformerServiceDeps
): HogTransformerService {
    const redis = createRedisV2PoolFromConfig({
        connection: config.CDP_REDIS_HOST
            ? {
                  url: config.CDP_REDIS_HOST,
                  options: { port: config.CDP_REDIS_PORT, password: config.CDP_REDIS_PASSWORD },
                  name: 'hog-transformer-redis',
              }
            : { url: config.REDIS_URL, name: 'hog-transformer-redis-fallback' },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })
    const redisReader = createCdpReaderRedisPool(config, redis, 'hog-transformer-redis')
    const valkeyShadow = createCdpValkeyShadowPools(config, 'hog-transformer-redis')

    const hogFunctionManager = new HogFunctionManagerService(deps.postgres, deps.pubSub, deps.encryptedFields)
    const hogInputsService = new HogInputsService(deps.integrationManager, config.ENCRYPTION_SALT_KEYS, config.SITE_URL)
    const trackingCodeSigner = new EmailTrackingCodeSigner(config.ENCRYPTION_SALT_KEYS, config.CDP_EMAIL_TRACKING_URL)
    const teamWorkflowsConfigService = new TeamWorkflowsConfigService(deps.postgres)
    const emailService = new EmailService(
        {
            sesAccessKeyId: config.SES_ACCESS_KEY_ID,
            sesSecretAccessKey: config.SES_SECRET_ACCESS_KEY,
            sesRegion: config.SES_REGION,
            sesEndpoint: config.SES_ENDPOINT,
        },
        deps.integrationManager,
        teamWorkflowsConfigService,
        config.ENCRYPTION_SALT_KEYS,
        config.SITE_URL,
        trackingCodeSigner
    )
    const recipientTokensService = new RecipientTokensService(config.ENCRYPTION_SALT_KEYS, config.SITE_URL)
    const hogExecutor = new HogExecutorService(
        {
            hogCostTimingUpperMs: config.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
            googleAdwordsDeveloperToken: config.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN,
            fetchRetries: config.CDP_FETCH_RETRIES,
            fetchBackoffBaseMs: config.CDP_FETCH_BACKOFF_BASE_MS,
            fetchBackoffMaxMs: config.CDP_FETCH_BACKOFF_MAX_MS,
        },
        { teamManager: deps.teamManager, siteUrl: config.SITE_URL },
        hogInputsService,
        emailService,
        recipientTokensService
    )
    const pluginExecutor = new LegacyPluginExecutorService(deps.postgres, deps.geoipService)
    const hogFunctionMonitoringService = new HogFunctionMonitoringService(deps.monitoringOutputs)
    const hogWatcherConfig = {
        hogCostTimingLowerMs: config.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS,
        hogCostTimingUpperMs: config.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
        hogCostTiming: config.CDP_WATCHER_HOG_COST_TIMING,
        asyncCostTimingLowerMs: config.CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS,
        asyncCostTimingUpperMs: config.CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS,
        asyncCostTiming: config.CDP_WATCHER_ASYNC_COST_TIMING,
        sendEvents: config.CDP_WATCHER_SEND_EVENTS,
        bucketSize: config.CDP_WATCHER_BUCKET_SIZE,
        refillRate: config.CDP_WATCHER_REFILL_RATE,
        ttl: config.CDP_WATCHER_TTL,
        automaticallyDisableFunctions: config.CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS,
        thresholdDegraded: config.CDP_WATCHER_THRESHOLD_DEGRADED,
        stateLockTtl: config.CDP_WATCHER_STATE_LOCK_TTL,
        observeResultsBufferTimeMs: config.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS,
        observeResultsBufferMaxResults: config.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS,
    }
    const hogWatcher = new HogWatcherService(deps.teamManager, hogWatcherConfig, redis, redisReader)
    // sendEvents:false on the mirror so we don't double-emit billable team events.
    const hogWatcherMirror: HogWatcherService | null = valkeyShadow
        ? new HogWatcherService(
              deps.teamManager,
              { ...hogWatcherConfig, sendEvents: false },
              valkeyShadow.writer,
              valkeyShadow.reader
          )
        : null

    return new HogTransformerService(
        hogFunctionManager,
        hogExecutor,
        hogWatcher,
        hogWatcherMirror,
        hogFunctionMonitoringService,
        pluginExecutor,
        deps.geoipService,
        redis,
        {
            siteUrl: config.SITE_URL,
            hogWatcherSampleRate: config.CDP_HOG_WATCHER_SAMPLE_RATE,
            hogRustVmShadowSampleRate: config.CDP_HOG_RUST_VM_SHADOW_SAMPLE_RATE,
            mmdbFileLocation: config.MMDB_FILE_LOCATION,
        }
    )
}
