import type { CdpConfig } from '@posthog/hog-engine/cdp/config'
import { HogFlow } from '@posthog/hog-engine/cdp/schema/hogflow'
import { HogInputsService } from '@posthog/hog-engine/cdp/services/hog-inputs.service'
import { LegacyPluginExecutorService } from '@posthog/hog-engine/cdp/services/legacy-plugin-executor.service'
import { HogFunctionManagerService } from '@posthog/hog-engine/cdp/services/managers/hog-function-manager.service'
import { RecipientsManagerService } from '@posthog/hog-engine/cdp/services/managers/recipients-manager.service'
import { HogFunctionMonitoringService } from '@posthog/hog-engine/cdp/services/monitoring/hog-function-monitoring.service'
import { HogFunctionType, HogFunctionTypeType } from '@posthog/hog-engine/cdp/types'
import { GroupReadRepository } from '@posthog/ingestion-common/groups/repositories/group-repository.interface'
import type { CommonConfig } from '@posthog/node-common/config'
import { RedisV2 } from '@posthog/node-common/redis/redis-v2'
import { QuotaLimiting } from '@posthog/node-common/services/quota-limiting.service'
import { GeoIPService } from '@posthog/node-common/utils/geoip'
import { logger } from '@posthog/node-common/utils/logger'

import {
    CdpCoreServicesConfig,
    CdpCoreServicesDeps,
    CdpOutputs,
    CdpValkeyShadowPools,
    createCdpCoreServices,
} from '~/cdp/cdp-services'
import { HogExecutorAsyncService } from '~/cdp/services/hog-executor-async.service'
import { HogFlowExecutorService } from '~/cdp/services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from '~/cdp/services/hogflows/hogflow-functions.service'
import { HogFlowManagerService } from '~/cdp/services/hogflows/hogflow-manager.service'
import { InvocationResultsService } from '~/cdp/services/invocation-results.service'
import { GroupsManagerService } from '~/cdp/services/managers/groups-manager.service'
import { HogFunctionTemplateManagerService } from '~/cdp/services/managers/hog-function-template-manager.service'
import { PersonsManagerService } from '~/cdp/services/managers/persons-manager.service'
import { EmailTrackingService } from '~/cdp/services/messaging/email-tracking.service'
import { EmailService } from '~/cdp/services/messaging/email.service'
import { RecipientPreferencesService } from '~/cdp/services/messaging/recipient-preferences.service'
import { HogMaskerService } from '~/cdp/services/monitoring/hog-masker.service'
import { HogWatcherService } from '~/cdp/services/monitoring/hog-watcher.service'
import { WorkflowsActivationReporter } from '~/cdp/services/monitoring/workflows-activation-reporter'
import { NativeDestinationExecutorService } from '~/cdp/services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from '~/cdp/services/segment-destination-executor.service'
import { CdpUsageReporterService } from '~/cdp/services/usage/cdp-usage-reporter.service'
import { HealthCheckResult, PluginServerService, Team, TeamId } from '~/types'

export type TeamWork = { team: Team; hogFunctions: HogFunctionType[]; hogFlows: HogFlow[] }

export type CdpConsumerBaseConfig = CdpCoreServicesConfig &
    Pick<CommonConfig, 'KAFKA_CLIENT_RACK'> &
    Pick<CdpConfig, 'CDP_OVERFLOW_QUEUE_ENABLED'>

export interface CdpConsumerBaseDeps extends CdpCoreServicesDeps {
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
    emailTrackingService: EmailTrackingService
    hogFunctionMonitoringService: HogFunctionMonitoringService
    workflowsActivationReporter: WorkflowsActivationReporter
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
        this.personsManager = services.personsManager
        this.recipientsManager = services.recipientsManager
        this.recipientPreferencesService = services.recipientPreferencesService
        this.hogFlowExecutor = services.hogFlowExecutor
        this.emailService = services.emailService
        this.emailTrackingService = services.emailTrackingService
        this.hogFunctionMonitoringService = services.hogFunctionMonitoringService
        this.workflowsActivationReporter = services.workflowsActivationReporter
        this.cdpUsageReporter = services.cdpUsageReporter
        this.invocationResultsService = services.invocationResultsService
        this.nativeDestinationExecutorService = services.nativeDestinationExecutorService
        this.segmentDestinationExecutorService = services.segmentDestinationExecutorService
        this.outputs = services.outputs

        // Base-only services
        this.hogMasker = new HogMaskerService(services.redis, services.valkeyShadow.writer)
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

    /** The team, or null when it has no hog function of these types and no hog flow. */
    protected async loadTeamWithHogFunctionsOrFlows(
        teamId: TeamId,
        hogTypes: HogFunctionTypeType[]
    ): Promise<Team | null> {
        return (await this.loadTeamWork(teamId, hogTypes))?.team ?? null
    }

    protected async loadTeamWork(teamId: TeamId, hogTypes: HogFunctionTypeType[]): Promise<TeamWork | null> {
        const [hogFunctions, hogFlows, team] = await Promise.all([
            this.hogFunctionManager.getHogFunctionsForTeam(teamId, hogTypes),
            this.hogFlowManager.getHogFlowsForTeam(teamId),
            this.deps.teamManager.getTeam(teamId),
        ])
        return team && (hogFunctions.length || hogFlows.length) ? { team, hogFunctions, hogFlows } : null
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
        // Release the per-consumer conversion-watcher pool created in createCdpCoreServices, so
        // graceful shutdown frees its cyclotron connections like the other cyclotron pools do.
        await this.invocationResultsService.stop()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public abstract isHealthy(): HealthCheckResult
}
