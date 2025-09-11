import { KafkaProducerWrapper } from '../../kafka/producer'
import { HealthCheckResult, Hub, PluginServerService, TeamId } from '../../types'
import { logger } from '../../utils/logger'
import { CdpRedis, createCdpRedisPool } from '../redis'
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

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export abstract class CdpConsumerBase {
    redis: CdpRedis
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

    constructor(protected hub: Hub) {
        this.redis = createCdpRedisPool(hub)
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogFlowManager = new HogFlowManagerService(hub)
        this.hogWatcher = new HogWatcherService(hub, this.redis)
        this.hogMasker = new HogMaskerService(this.redis)
        this.hogExecutor = new HogExecutorService(this.hub)
        this.hogFunctionTemplateManager = new HogFunctionTemplateManagerService(this.hub)
        this.hogFlowFunctionsService = new HogFlowFunctionsService(
            this.hub,
            this.hogFunctionTemplateManager,
            this.hogExecutor
        )

        this.recipientsManager = new RecipientsManagerService(this.hub)
        this.recipientPreferencesService = new RecipientPreferencesService(this.recipientsManager)
        this.hogFlowExecutor = new HogFlowExecutorService(
            this.hogFlowFunctionsService,
            this.recipientPreferencesService
        )

        this.personsManager = new PersonsManagerService(this.hub.personRepository)
        this.groupsManager = new GroupsManagerService(this.hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(this.hub)
        this.pluginDestinationExecutorService = new LegacyPluginExecutorService(this.hub)
        this.nativeDestinationExecutorService = new NativeDestinationExecutorService(this.hub)
        this.segmentDestinationExecutorService = new SegmentDestinationExecutorService(this.hub)
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
            KafkaProducerWrapper.create(this.hub).then((producer) => {
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
