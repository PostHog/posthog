import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'

import { Hub } from '../types'
import { HogExecutorService } from './services/hog-executor.service'
import { HogInputsService } from './services/hog-inputs.service'
import { HogFlowExecutorService } from './services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from './services/hogflows/hogflow-functions.service'
import { HogFlowManagerService } from './services/hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from './services/managers/hog-function-manager.service'
import { HogFunctionTemplateManagerService } from './services/managers/hog-function-template-manager.service'
import { RecipientsManagerService } from './services/managers/recipients-manager.service'
import { EmailService } from './services/messaging/email.service'
import { RecipientPreferencesService } from './services/messaging/recipient-preferences.service'
import { RecipientTokensService } from './services/messaging/recipient-tokens.service'
import { HogFunctionMonitoringService } from './services/monitoring/hog-function-monitoring.service'
import { HogWatcherService } from './services/monitoring/hog-watcher.service'
import { NativeDestinationExecutorService } from './services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from './services/segment-destination-executor.service'

export interface CdpCoreServices {
    redis: RedisV2
    hogFunctionManager: HogFunctionManagerService
    hogFlowManager: HogFlowManagerService
    hogWatcher: HogWatcherService
    hogExecutor: HogExecutorService
    hogFunctionTemplateManager: HogFunctionTemplateManagerService
    hogFlowFunctionsService: HogFlowFunctionsService
    recipientsManager: RecipientsManagerService
    recipientPreferencesService: RecipientPreferencesService
    hogFlowExecutor: HogFlowExecutorService
    hogFunctionMonitoringService: HogFunctionMonitoringService
    nativeDestinationExecutorService: NativeDestinationExecutorService
    segmentDestinationExecutorService: SegmentDestinationExecutorService
    recipientTokensService: RecipientTokensService
}

// Transitional type — will shrink as callers migrate off Hub
export type CdpCoreServicesDeps = Pick<
    Hub,
    // Redis config
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'CDP_REDIS_HOST'
    | 'CDP_REDIS_PORT'
    | 'CDP_REDIS_PASSWORD'
    // HogFunctionManagerService
    | 'postgres'
    | 'pubSub'
    | 'encryptedFields'
    // HogWatcherService
    | 'teamManager'
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
    // HogExecutorService
    | 'integrationManager'
    | 'ENCRYPTION_SALT_KEYS'
    | 'SITE_URL'
    | 'SES_ACCESS_KEY_ID'
    | 'SES_SECRET_ACCESS_KEY'
    | 'SES_REGION'
    | 'SES_ENDPOINT'
    | 'CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN'
    | 'CDP_FETCH_RETRIES'
    | 'CDP_FETCH_BACKOFF_BASE_MS'
    | 'CDP_FETCH_BACKOFF_MAX_MS'
    // HogFunctionMonitoringService
    | 'kafkaProducer'
    | 'internalCaptureService'
    | 'HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC'
    | 'HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC'
>

export function createCdpCoreServices(hub: CdpCoreServicesDeps, redisName = 'cdp-redis'): CdpCoreServices {
    const redis = createRedisV2PoolFromConfig({
        connection: hub.CDP_REDIS_HOST
            ? {
                  url: hub.CDP_REDIS_HOST,
                  options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  name: redisName,
              }
            : { url: hub.REDIS_URL, name: `${redisName}-fallback` },
        poolMinSize: hub.REDIS_POOL_MIN_SIZE,
        poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
    })

    const hogFunctionManager = new HogFunctionManagerService(hub.postgres, hub.pubSub, hub.encryptedFields)
    const hogFlowManager = new HogFlowManagerService(hub.postgres, hub.pubSub)

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

    const hogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub.postgres)
    const hogFlowFunctionsService = new HogFlowFunctionsService(hub.SITE_URL, hogFunctionTemplateManager, hogExecutor)

    const recipientsManager = new RecipientsManagerService(hub.postgres)
    const recipientPreferencesService = new RecipientPreferencesService(recipientsManager)
    const hogFlowExecutor = new HogFlowExecutorService(hogFlowFunctionsService, recipientPreferencesService)

    const hogFunctionMonitoringService = new HogFunctionMonitoringService(
        hub.kafkaProducer,
        hub.internalCaptureService,
        hub.teamManager,
        hub.HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC,
        hub.HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC
    )

    const nativeDestinationExecutorService = new NativeDestinationExecutorService(hub)
    const segmentDestinationExecutorService = new SegmentDestinationExecutorService(hub)

    return {
        redis,
        hogFunctionManager,
        hogFlowManager,
        hogWatcher,
        hogExecutor,
        hogFunctionTemplateManager,
        hogFlowFunctionsService,
        recipientsManager,
        recipientPreferencesService,
        hogFlowExecutor,
        hogFunctionMonitoringService,
        nativeDestinationExecutorService,
        segmentDestinationExecutorService,
        recipientTokensService,
    }
}
