import { RedisV2 } from '~/common/redis/redis-v2'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { HealthCheckResult, PluginServerService, PluginsServerConfig, TeamId } from '../../types'
import { GeoIPService } from '../../utils/geoip'
import { logger } from '../../utils/logger'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonRepository } from '../../worker/ingestion/persons/repositories/person-repository'
import { CdpCoreServicesConfig, CdpCoreServicesDeps, createCdpCoreServices } from '../cdp-services'
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

export type CdpConsumerBaseConfig = CdpCoreServicesConfig &
    Pick<PluginsServerConfig, 'KAFKA_CLIENT_RACK' | 'CDP_OVERFLOW_QUEUE_ENABLED'>

export interface CdpConsumerBaseDeps extends CdpCoreServicesDeps {
    personRepository: PersonRepository
    geoipService: GeoIPService
    groupRepository: GroupRepository
    quotaLimiting: QuotaLimiting
}

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export abstract class CdpConsumerBase<TConfig extends CdpConsumerBaseConfig = CdpConsumerBaseConfig> {
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

    constructor(
        protected config: TConfig,
        protected deps: CdpConsumerBaseDeps
    ) {
        const services = createCdpCoreServices(config, deps)

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
        this.personsManager = new PersonsManagerService(deps.personRepository)
        this.groupsManager = new GroupsManagerService(deps.teamManager, deps.groupRepository)
        this.pluginDestinationExecutorService = new LegacyPluginExecutorService(deps.postgres, deps.geoipService)
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
            KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK).then((producer) => {
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
