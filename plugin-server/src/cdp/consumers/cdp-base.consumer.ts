import { KafkaProducerWrapper } from '../../kafka/producer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, PluginServerService, TeamId } from '../../types'
import { logger } from '../../utils/logger'
import { CdpRedis, createCdpRedisPool } from '../redis'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogFlowExecutorService } from '../services/hogflows/hogflow-executor.service'
import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { GroupsManagerService } from '../services/managers/groups-manager.service'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionTemplateManagerService } from '../services/managers/hog-function-template-manager.service'
import { PersonsManagerService } from '../services/managers/persons-manager.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogMaskerService } from '../services/monitoring/hog-masker.service'
import { HogWatcherService } from '../services/monitoring/hog-watcher.service'

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export abstract class CdpConsumerBase {
    hogFunctionManager: HogFunctionManagerService
    hogFlowManager: HogFlowManagerService
    hogExecutor: HogExecutorService
    hogFlowExecutor: HogFlowExecutorService
    hogWatcher: HogWatcherService
    hogMasker: HogMaskerService
    personsManager: PersonsManagerService
    groupsManager: GroupsManagerService
    isStopping = false
    hogFunctionMonitoringService: HogFunctionMonitoringService
    redis: CdpRedis
    hogFunctionTemplateManager: HogFunctionTemplateManagerService

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
        this.hogFlowExecutor = new HogFlowExecutorService(this.hub, this.hogExecutor, this.hogFunctionTemplateManager)
        this.personsManager = new PersonsManagerService(this.hub)
        this.groupsManager = new GroupsManagerService(this.hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(this.hub)
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    protected runInstrumented<T>(name: string, func: () => Promise<T>): Promise<T> {
        return runInstrumentedFunction<T>({ statsKey: `cdpConsumer.${name}`, func })
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

    public abstract isHealthy(): boolean
}
