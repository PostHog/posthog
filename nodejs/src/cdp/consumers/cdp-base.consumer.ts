import { GroupReadRepository } from '~/common/groups/repositories/group-repository.interface'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { RedisV2 } from '~/common/redis/redis-v2'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { GeoIPService } from '~/common/utils/geoip'
import { logger } from '~/common/utils/logger'

import type { CommonConfig } from '../../common/config'
import { HealthCheckResult, PluginServerService, TeamId } from '../../types'
import {
    CdpCoreServicesConfig,
    CdpCoreServicesDeps,
    CdpOutputs,
    CdpValkeyShadowPools,
    createCdpCoreServices,
} from '../cdp-services'
import type { CdpConfig } from '../config'
import { HogExecutorAsyncService } from '../services/hog-executor-async.service'
import { HogInputsService } from '../services/hog-inputs.service'
import { HogFlowExecutorService } from '../services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from '../services/hogflows/hogflow-functions.service'
import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { InvocationResultsService } from '../services/invocation-results.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { GroupsManagerService } from '../services/managers/groups-manager.service'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionTemplateManagerService } from '../services/managers/hog-function-template-manager.service'
import { PersonsManagerService } from '../services/managers/persons-manager.service'
import { RecipientsManagerService } from '../services/managers/recipients-manager.service'
import { EmailService } from '../services/messaging/email.service'
import { RecipientPreferencesService } from '../services/messaging/recipient-preferences.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogMaskerService } from '../services/monitoring/hog-masker.service'
import { HogWatcherService } from '../services/monitoring/hog-watcher.service'
import { NativeDestinationExecutorService } from '../services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from '../services/segment-destination-executor.service'
import { CdpUsageReporterService } from '../services/usage/cdp-usage-reporter.service'

export type CdpConsumerBaseConfig = CdpCoreServicesConfig &
    Pick<CommonConfig, 'KAFKA_CLIENT_RACK'> &
    Pick<CdpConfig, 'CDP_OVERFLOW_QUEUE_ENABLED'>

export interface CdpConsumerBaseDeps extends CdpCoreServicesDeps {
    personRepository: PersonReadRepository
    geoipService: GeoIPService
    groupRepository: GroupReadRepository
    quotaLimiting: QuotaLimiting
}

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export abstract class CdpConsumerBase<TConfig extends CdpConsumerBaseConfig = CdpConsumerBaseConfig> {
    redis: RedisV2
    valkeyShadow: CdpValkeyShadowPools
    isStopping = false

    hogExecutorAsync: HogExecutorAsyncService
    hogInputsService: HogInputsService
    hogFlowExecutor: HogFlowExecutorService
    hogMasker: HogMaskerService
    hogWatcher: HogWatcherService
    hogWatcherMirror: HogWatcherService

    groupsManager: GroupsManagerService
    hogFlowManager: HogFlowManagerService
    hogFunctionManager: HogFunctionManagerService
    hogFunctionTemplateManager: HogFunctionTemplateManagerService
    hogFlowFunctionsService: HogFlowFunctionsService
    personsManager: PersonsManagerService
    recipientsManager: RecipientsManagerService

    emailService: EmailService
    hogFunctionMonitoringService: HogFunctionMonitoringService
    cdpUsageReporter: CdpUsageReporterService
    invocationResultsService: InvocationResultsService
    nativeDestinationExecutorService: NativeDestinationExecutorService
    pluginDestinationExecutorService: LegacyPluginExecutorService
    recipientPreferencesService: RecipientPreferencesService
    segmentDestinationExecutorService: SegmentDestinationExecutorService

    protected outputs: CdpOutputs
    protected abstract name: string

    constructor(
        protected config: TConfig,
        protected deps: CdpConsumerBaseDeps
    ) {
        const services = createCdpCoreServices(config, deps)

        this.redis = services.redis
        this.valkeyShadow = services.valkeyShadow
        this.hogFunctionManager = services.hogFunctionManager
        this.hogFlowManager = services.hogFlowManager
        this.hogWatcher = services.hogWatcher
        this.hogWatcherMirror = services.hogWatcherMirror
        this.hogExecutorAsync = services.hogExecutorAsync
        this.hogInputsService = services.hogInputsService
        this.hogFunctionTemplateManager = services.hogFunctionTemplateManager
        this.hogFlowFunctionsService = services.hogFlowFunctionsService
        this.recipientsManager = services.recipientsManager
        this.recipientPreferencesService = services.recipientPreferencesService
        this.hogFlowExecutor = services.hogFlowExecutor
        this.emailService = services.emailService
        this.hogFunctionMonitoringService = services.hogFunctionMonitoringService
        this.cdpUsageReporter = services.cdpUsageReporter
        this.invocationResultsService = services.invocationResultsService
        this.nativeDestinationExecutorService = services.nativeDestinationExecutorService
        this.segmentDestinationExecutorService = services.segmentDestinationExecutorService
        this.outputs = services.outputs

        // Base-only services
        this.hogMasker = new HogMaskerService(services.redis, services.valkeyShadow.writer)
        this.personsManager = new PersonsManagerService(deps.teamManager, deps.personRepository, config.SITE_URL)
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

    public async start(): Promise<void> {
        // Outputs are resolved in the constructor via `createCdpCoreServices` — no
        // per-consumer producer lifecycle. The outer server owns producer shutdown
        // through `cdpProducerRegistry.disconnectAll()`.
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true
        // Billing records live only in memory until they are sent, so a graceful stop drains them.
        await this.cdpUsageReporter.shutdown()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public abstract isHealthy(): HealthCheckResult
}
