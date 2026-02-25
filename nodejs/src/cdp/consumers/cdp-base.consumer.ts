import { RedisV2 } from '~/common/redis/redis-v2'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { HealthCheckResult, Hub, PluginServerService, TeamId } from '../../types'
import { logger } from '../../utils/logger'
import { createCdpCoreServices } from '../cdp-services'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogFlowExecutorService } from '../services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from '../services/hogflows/hogflow-functions.service'
import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { GroupsManagerService } from '../services/managers/groups-manager.service'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionTemplateManagerService } from '../services/managers/hog-function-template-manager.service'
import { PersonsManagerService } from '../services/managers/persons-manager.service'
import { RecipientsManagerService } from '../services/managers/recipients-manager.service'
import { RecipientPreferencesService } from '../services/messaging/recipient-preferences.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogMaskerService } from '../services/monitoring/hog-masker.service'
import { HogWatcherService } from '../services/monitoring/hog-watcher.service'
import { NativeDestinationExecutorService } from '../services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from '../services/segment-destination-executor.service'

/**
 * Combined Hub type for CdpConsumerBase and all CDP consumers.
 * This includes all fields needed by the base consumer and its services.
 */
export type CdpConsumerBaseHub = Pick<
    Hub,
    // Redis config
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'CDP_REDIS_HOST'
    | 'CDP_REDIS_PORT'
    | 'CDP_REDIS_PASSWORD'
    // KafkaProducerWrapper.create
    | 'KAFKA_CLIENT_RACK'
    // PersonsManagerService needs personRepository
    | 'personRepository'
    // QuotaLimiting
    | 'quotaLimiting'
    // CDP overflow queue
    | 'CDP_OVERFLOW_QUEUE_ENABLED'
    // LegacyPluginExecutorService
    | 'postgres'
    | 'geoipService'
    // HogFlowManagerService
    | 'pubSub'
    // HogFunctionManagerService
    | 'encryptedFields'
    // HogFunctionMonitoringService
    | 'teamManager'
    | 'kafkaProducer'
    | 'internalCaptureService'
    | 'HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC'
    | 'HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC'
    // GroupsManagerService
    | 'groupRepository'
    // HogExecutorService
    | 'integrationManager'
    | 'ENCRYPTION_SALT_KEYS'
    | 'SITE_URL'
    | 'SES_ACCESS_KEY_ID'
    | 'SES_SECRET_ACCESS_KEY'
    | 'SES_REGION'
    | 'SES_ENDPOINT'
    | 'CDP_WATCHER_HOG_COST_TIMING_UPPER_MS'
    | 'CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN'
    | 'CDP_FETCH_RETRIES'
    | 'CDP_FETCH_BACKOFF_BASE_MS'
    | 'CDP_FETCH_BACKOFF_MAX_MS'
    // HogWatcherService
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

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export abstract class CdpConsumerBase<THub extends CdpConsumerBaseHub = CdpConsumerBaseHub> {
    redis: RedisV2
    isStopping = false

    hogExecutor: HogExecutorService
    hogFlowExecutor: HogFlowExecutorService
    hogMasker: HogMaskerService
    hogWatcher: HogWatcherService

    groupsManager: GroupsManagerService
    hogFlowManager: HogFlowManagerService
    hogFunctionManager: HogFunctionManagerService
    hogFunctionTemplateManager: HogFunctionTemplateManagerService
    hogFlowFunctionsService: HogFlowFunctionsService
    personsManager: PersonsManagerService
    recipientsManager: RecipientsManagerService

    hogFunctionMonitoringService: HogFunctionMonitoringService
    nativeDestinationExecutorService: NativeDestinationExecutorService
    pluginDestinationExecutorService: LegacyPluginExecutorService
    recipientPreferencesService: RecipientPreferencesService
    segmentDestinationExecutorService: SegmentDestinationExecutorService

    protected kafkaProducer?: KafkaProducerWrapper
    protected abstract name: string

    protected heartbeat = () => {}

    constructor(protected hub: THub) {
        const services = createCdpCoreServices(hub)

        this.redis = services.redis
        this.hogFunctionManager = services.hogFunctionManager
        this.hogFlowManager = services.hogFlowManager
        this.hogWatcher = services.hogWatcher
        this.hogExecutor = services.hogExecutor
        this.hogFunctionTemplateManager = services.hogFunctionTemplateManager
        this.hogFlowFunctionsService = services.hogFlowFunctionsService
        this.recipientsManager = services.recipientsManager
        this.recipientPreferencesService = services.recipientPreferencesService
        this.hogFlowExecutor = services.hogFlowExecutor
        this.hogFunctionMonitoringService = services.hogFunctionMonitoringService
        this.nativeDestinationExecutorService = services.nativeDestinationExecutorService
        this.segmentDestinationExecutorService = services.segmentDestinationExecutorService

        // Base-only services
        this.hogMasker = new HogMaskerService(services.redis)
        this.personsManager = new PersonsManagerService(hub.personRepository)
        this.groupsManager = new GroupsManagerService(hub.teamManager, hub.groupRepository)
        this.pluginDestinationExecutorService = new LegacyPluginExecutorService(hub.postgres, hub.geoipService)
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    protected async runWithHeartbeat<T>(func: () => Promise<T> | T): Promise<T> {
        // Helper function to ensure that looping over lots of hog functions doesn't block up the thread, killing the consumer
        const res = await func()
        this.heartbeat()
        await new Promise((resolve) => process.nextTick(resolve))

        return res
    }

    public async start(): Promise<void> {
        // NOTE: This is only for starting shared services
        await Promise.all([
            KafkaProducerWrapper.create(this.hub.KAFKA_CLIENT_RACK).then((producer) => {
                this.kafkaProducer = producer
            }),
        ])
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        logger.info('🔁', `${this.name} - stopping kafka producer`)
        await this.kafkaProducer?.disconnect()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public abstract isHealthy(): HealthCheckResult
}
