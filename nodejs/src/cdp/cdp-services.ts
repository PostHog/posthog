import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { getRedisHost } from '~/utils/db/redis'

import type { CommonConfig } from '../common/config'
import { InternalCaptureService } from '../common/services/internal-capture'
import { AppMetricsOutput, LogEntriesOutput } from '../ingestion/common/outputs'
import { IngestionOutputs } from '../ingestion/outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '../ingestion/outputs/kafka-producer-registry'
import { PostgresRouter } from '../utils/db/postgres'
import { logger } from '../utils/logger'
import { PubSub } from '../utils/pubsub'
import { TeamManager } from '../utils/team-manager'
import type { CdpConfig } from './config'
import {
    BatchHogflowRequestsOutput,
    PrecalculatedPersonPropertiesOutput,
    PrefilteredEventsOutput,
    WarehouseSourceWebhooksOutput,
} from './outputs/outputs'
import { CdpProducerName } from './outputs/producers'
import { createCdpOutputsRegistry } from './outputs/registry'
import { CapturedEventsService } from './services/captured-events/captured-events.service'
import { HogExecutorService } from './services/hog-executor.service'
import { HogInputsService } from './services/hog-inputs.service'
import { HogFlowExecutorService } from './services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from './services/hogflows/hogflow-functions.service'
import { HogFlowManagerService } from './services/hogflows/hogflow-manager.service'
import { InvocationResultsService } from './services/invocation-results.service'
import { HogFunctionManagerService } from './services/managers/hog-function-manager.service'
import { HogFunctionTemplateManagerService } from './services/managers/hog-function-template-manager.service'
import { IntegrationManagerService } from './services/managers/integration-manager.service'
import { RecipientsManagerService } from './services/managers/recipients-manager.service'
import { EmailService } from './services/messaging/email.service'
import { RecipientPreferencesService } from './services/messaging/recipient-preferences.service'
import { RecipientTokensService } from './services/messaging/recipient-tokens.service'
import { HogFunctionMonitoringService } from './services/monitoring/hog-function-monitoring.service'
import { HogWatcherService } from './services/monitoring/hog-watcher.service'
import { NativeDestinationExecutorService } from './services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from './services/segment-destination-executor.service'
import { WarehouseWebhooksService } from './services/warehouse/warehouse-webhooks.service'
import { EncryptedFields } from './utils/encryption-utils'

/** Union of every output name resolved by `createCdpOutputsRegistry()`. */
export type CdpOutput =
    | AppMetricsOutput
    | LogEntriesOutput
    | PrefilteredEventsOutput
    | PrecalculatedPersonPropertiesOutput
    | BatchHogflowRequestsOutput
    | WarehouseSourceWebhooksOutput

export type CdpOutputs = IngestionOutputs<CdpOutput>

export interface CdpValkeyShadowPools {
    writer: RedisV2
    reader: RedisV2
}

export interface CdpCoreServices {
    redis: RedisV2
    /**
     * Shadow Valkey pools used for dual-write/read load testing. Null when
     * CDP_VALKEY_DUAL_ENABLED is false or CDP_VALKEY_HOST is unset. Consumers
     * that build their own redis-backed services (e.g. CdpEventsConsumer's
     * HogRateLimiterService) read this to construct mirror instances bound
     * to the shadow Valkey.
     */
    valkeyShadow: CdpValkeyShadowPools | null
    hogFunctionManager: HogFunctionManagerService
    hogFlowManager: HogFlowManagerService
    hogWatcher: HogWatcherService
    /**
     * Mirror HogWatcherService bound to the shadow Valkey pool. Null when
     * shadow mode is disabled. Use at call sites alongside `hogWatcher` (via
     * `mirrorCall`) to load-test the new infrastructure. Constructed with
     * `sendEvents: false` so it never emits duplicate billable team events.
     */
    hogWatcherMirror: HogWatcherService | null
    hogExecutor: HogExecutorService
    hogFunctionTemplateManager: HogFunctionTemplateManagerService
    hogFlowFunctionsService: HogFlowFunctionsService
    recipientsManager: RecipientsManagerService
    recipientPreferencesService: RecipientPreferencesService
    hogFlowExecutor: HogFlowExecutorService
    hogFunctionMonitoringService: HogFunctionMonitoringService
    /** Fans `CyclotronJobInvocationResult` batches across monitoring / warehouse / captured-events. */
    invocationResultsService: InvocationResultsService
    nativeDestinationExecutorService: NativeDestinationExecutorService
    segmentDestinationExecutorService: SegmentDestinationExecutorService
    recipientTokensService: RecipientTokensService
    /** Resolved outputs shared across every CDP service/consumer. */
    outputs: CdpOutputs
}

export type CdpCoreServicesConfig = Pick<
    CommonConfig,
    'REDIS_URL' | 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE' | 'ENCRYPTION_SALT_KEYS' | 'SITE_URL'
> &
    Pick<
        CdpConfig,
        | 'CDP_REDIS_HOST'
        | 'CDP_REDIS_PORT'
        | 'CDP_REDIS_PASSWORD'
        | 'CDP_REDIS_READER_HOST'
        | 'CDP_REDIS_READER_PORT'
        | 'CDP_VALKEY_HOST'
        | 'CDP_VALKEY_PORT'
        | 'CDP_VALKEY_PASSWORD'
        | 'CDP_VALKEY_READER_HOST'
        | 'CDP_VALKEY_READER_PORT'
        | 'CDP_VALKEY_DUAL_ENABLED'
        | 'CDP_VALKEY_TLS'
        | 'CDP_WATCHER_HOG_COST_TIMING_LOWER_MS'
        | 'CDP_WATCHER_HOG_COST_TIMING_UPPER_MS'
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
        | 'SES_ACCESS_KEY_ID'
        | 'SES_SECRET_ACCESS_KEY'
        | 'SES_REGION'
        | 'SES_ENDPOINT'
        | 'CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN'
        | 'CDP_FETCH_RETRIES'
        | 'CDP_FETCH_BACKOFF_BASE_MS'
        | 'CDP_FETCH_BACKOFF_MAX_MS'
        | 'HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC'
        | 'HOG_FUNCTION_MONITORING_APP_METRICS_PRODUCER'
        | 'HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC'
        | 'HOG_FUNCTION_MONITORING_LOG_ENTRIES_PRODUCER'
        | 'CDP_PREFILTERED_EVENTS_TOPIC'
        | 'CDP_PREFILTERED_EVENTS_PRODUCER'
        | 'CDP_PRECALCULATED_PERSON_PROPERTIES_TOPIC'
        | 'CDP_PRECALCULATED_PERSON_PROPERTIES_PRODUCER'
        | 'CDP_BATCH_HOGFLOW_REQUESTS_TOPIC'
        | 'CDP_BATCH_HOGFLOW_REQUESTS_PRODUCER'
        | 'CDP_WAREHOUSE_SOURCE_WEBHOOKS_TOPIC'
        | 'CDP_WAREHOUSE_SOURCE_WEBHOOKS_PRODUCER'
    >

export interface CdpCoreServicesDeps {
    postgres: PostgresRouter
    pubSub: PubSub
    encryptedFields: EncryptedFields
    teamManager: TeamManager
    integrationManager: IntegrationManagerService
    /** Registry of producers backing the CDP outputs (DEFAULT / MSK / Warpstream-ingestion / Warehouse). */
    cdpProducerRegistry: KafkaProducerRegistry<CdpProducerName>
    internalCaptureService: InternalCaptureService
}

/**
 * Creates a Redis reader pool, using a dedicated reader host if configured,
 * otherwise falling back to the writer pool.
 */
export function createCdpReaderRedisPool(
    config: Pick<
        CdpCoreServicesConfig,
        | 'CDP_REDIS_HOST'
        | 'CDP_REDIS_PORT'
        | 'CDP_REDIS_PASSWORD'
        | 'CDP_REDIS_READER_HOST'
        | 'CDP_REDIS_READER_PORT'
        | 'REDIS_URL'
        | 'REDIS_POOL_MIN_SIZE'
        | 'REDIS_POOL_MAX_SIZE'
    >,
    writerPool: RedisV2,
    name: string
): RedisV2 {
    if (config.CDP_REDIS_READER_HOST) {
        logger.info(
            '🔌',
            `[${name}] writer=${config.CDP_REDIS_HOST}:${config.CDP_REDIS_PORT} reader=${config.CDP_REDIS_READER_HOST}:${config.CDP_REDIS_READER_PORT}`
        )
        const readerPool = createRedisV2PoolFromConfig({
            connection: {
                url: config.CDP_REDIS_READER_HOST,
                options: { port: config.CDP_REDIS_READER_PORT, password: config.CDP_REDIS_PASSWORD },
                name: `${name}-reader`,
            },
            poolMinSize: config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        })

        // Non-blocking startup health check — surfaces misconfig immediately in logs
        void readerPool
            .useClient({ name: 'startup-ping', timeout: 5000 }, (client) => client.ping())
            .catch((err) => {
                logger.error(
                    '🔌',
                    `[${name}] reader at ${config.CDP_REDIS_READER_HOST}:${config.CDP_REDIS_READER_PORT} failed startup health check — reads will fall back to writer`,
                    { err }
                )
            })

        return readerPool
    }

    const sanitizedWriter = config.CDP_REDIS_HOST || getRedisHost(config.REDIS_URL)
    logger.info('🔌', `[${name}] writer=${sanitizedWriter}:${config.CDP_REDIS_PORT} reader=<falling back to writer>`)
    return writerPool
}

/**
 * Creates writer + reader pools for the shadow Valkey instance used in dual-write/read mode.
 * Returns null when CDP_VALKEY_DUAL_ENABLED is false or CDP_VALKEY_HOST is unset, in which
 * case the shadow path is disabled and behavior is identical to today.
 *
 * The reader falls back to the writer pool when CDP_VALKEY_READER_HOST is unset.
 */
export function createCdpValkeyShadowPools(
    config: Pick<
        CdpCoreServicesConfig,
        | 'CDP_VALKEY_HOST'
        | 'CDP_VALKEY_PORT'
        | 'CDP_VALKEY_PASSWORD'
        | 'CDP_VALKEY_READER_HOST'
        | 'CDP_VALKEY_READER_PORT'
        | 'CDP_VALKEY_DUAL_ENABLED'
        | 'CDP_VALKEY_TLS'
        | 'REDIS_POOL_MIN_SIZE'
        | 'REDIS_POOL_MAX_SIZE'
    >,
    name: string
): CdpValkeyShadowPools | null {
    if (!config.CDP_VALKEY_DUAL_ENABLED || !config.CDP_VALKEY_HOST) {
        return null
    }

    logger.info(
        '🪞',
        `[${name}] shadow valkey writer=${config.CDP_VALKEY_HOST}:${config.CDP_VALKEY_PORT} reader=${config.CDP_VALKEY_READER_HOST || '<falling back to writer>'}`
    )

    // commandTimeout aborts in-flight commands at the ioredis protocol level, so a slow shadow
    // doesn't tie up a pool client until the kernel TCP timeout. Pair this with mirrorCall()'s
    // race-timeout (which only stops awaiting); together they prevent leaks on bad shadow health.
    const shadowCommandTimeoutMs = 1000

    const tls = config.CDP_VALKEY_TLS ? {} : undefined

    const writer = createRedisV2PoolFromConfig({
        connection: {
            url: config.CDP_VALKEY_HOST,
            options: {
                port: config.CDP_VALKEY_PORT,
                password: config.CDP_VALKEY_PASSWORD,
                commandTimeout: shadowCommandTimeoutMs,
                tls,
            },
            name: `${name}-shadow`,
        },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })

    // Non-blocking startup health check — shadow misconfig must not block startup.
    void writer
        .useClient({ name: 'startup-ping', timeout: 5000 }, (client) => client.ping())
        .catch((err) => {
            logger.error(
                '🪞',
                `[${name}] shadow writer at ${config.CDP_VALKEY_HOST}:${config.CDP_VALKEY_PORT} failed startup health check — shadow ops will surface as "[mirror:*] failed" warn logs from mirrorCall()`,
                { err }
            )
        })

    let reader: RedisV2 = writer
    if (config.CDP_VALKEY_READER_HOST) {
        reader = createRedisV2PoolFromConfig({
            connection: {
                url: config.CDP_VALKEY_READER_HOST,
                options: {
                    port: config.CDP_VALKEY_READER_PORT,
                    password: config.CDP_VALKEY_PASSWORD,
                    commandTimeout: shadowCommandTimeoutMs,
                    tls,
                },
                name: `${name}-shadow-reader`,
            },
            poolMinSize: config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        })

        void reader
            .useClient({ name: 'startup-ping', timeout: 5000 }, (client) => client.ping())
            .catch((err) => {
                logger.error(
                    '🪞',
                    `[${name}] shadow reader at ${config.CDP_VALKEY_READER_HOST}:${config.CDP_VALKEY_READER_PORT} failed startup health check`,
                    { err }
                )
            })
    }

    return { writer, reader }
}

export function createCdpCoreServices(
    config: CdpCoreServicesConfig,
    deps: CdpCoreServicesDeps,
    redisName = 'cdp-redis'
): CdpCoreServices {
    const redis = createRedisV2PoolFromConfig({
        connection: config.CDP_REDIS_HOST
            ? {
                  url: config.CDP_REDIS_HOST,
                  options: { port: config.CDP_REDIS_PORT, password: config.CDP_REDIS_PASSWORD },
                  name: redisName,
              }
            : { url: config.REDIS_URL, name: `${redisName}-fallback` },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })

    const redisReader = createCdpReaderRedisPool(config, redis, redisName)
    const valkeyShadow = createCdpValkeyShadowPools(config, redisName)

    const hogFunctionManager = new HogFunctionManagerService(deps.postgres, deps.pubSub, deps.encryptedFields)
    const hogFlowManager = new HogFlowManagerService(deps.postgres, deps.pubSub)

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

    // Mirror HogWatcherService bound to the shadow Valkey pool. `sendEvents: false`
    // so it never emits duplicate billable team events on state transitions; the
    // Prom counter `cdp_hog_function_state_change` may double-emit when both pools
    // detect the same transition — rare, accepted during dual-write mode. The
    // mirror dispatches to the optimized V3 lua so we get full-load comparison
    // data on the optimized path.
    const hogWatcherMirror: HogWatcherService | null = valkeyShadow
        ? new HogWatcherService(
              deps.teamManager,
              { ...hogWatcherConfig, sendEvents: false, useV3: true },
              valkeyShadow.writer,
              valkeyShadow.reader
          )
        : null

    const hogInputsService = new HogInputsService(deps.integrationManager, config.ENCRYPTION_SALT_KEYS, config.SITE_URL)
    const emailService = new EmailService(
        {
            sesAccessKeyId: config.SES_ACCESS_KEY_ID,
            sesSecretAccessKey: config.SES_SECRET_ACCESS_KEY,
            sesRegion: config.SES_REGION,
            sesEndpoint: config.SES_ENDPOINT,
        },
        deps.integrationManager,
        config.ENCRYPTION_SALT_KEYS,
        config.SITE_URL
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

    const hogFunctionTemplateManager = new HogFunctionTemplateManagerService(deps.postgres)
    const hogFlowFunctionsService = new HogFlowFunctionsService(
        config.SITE_URL,
        hogFunctionTemplateManager,
        hogExecutor
    )

    const recipientsManager = new RecipientsManagerService(deps.postgres)
    const recipientPreferencesService = new RecipientPreferencesService(recipientsManager)
    const hogFlowExecutor = new HogFlowExecutorService(hogFlowFunctionsService, recipientPreferencesService, redis)

    const outputs = createCdpOutputsRegistry().build(deps.cdpProducerRegistry, config)

    const hogFunctionMonitoringService = new HogFunctionMonitoringService(outputs)
    const warehouseWebhooksService = new WarehouseWebhooksService(outputs)
    const capturedEventsService = new CapturedEventsService(deps.internalCaptureService, deps.teamManager)
    const invocationResultsService = new InvocationResultsService(
        hogFunctionMonitoringService,
        warehouseWebhooksService,
        capturedEventsService
    )

    const nativeDestinationExecutorService = new NativeDestinationExecutorService(config)
    const segmentDestinationExecutorService = new SegmentDestinationExecutorService(config)

    return {
        redis,
        valkeyShadow,
        hogFunctionManager,
        hogFlowManager,
        hogWatcher,
        hogWatcherMirror,
        hogExecutor,
        hogFunctionTemplateManager,
        hogFlowFunctionsService,
        recipientsManager,
        recipientPreferencesService,
        hogFlowExecutor,
        hogFunctionMonitoringService,
        invocationResultsService,
        nativeDestinationExecutorService,
        segmentDestinationExecutorService,
        recipientTokensService,
        outputs,
    }
}
