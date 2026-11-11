import type { CommonConfig, HubServices as CommonHubServices } from '@posthog/node-common/types'

import type { CdpConfig } from './cdp/config'
import type {
    KafkaWarehouseProducerEnvConfig,
    KafkaWarpstreamCyclotronProducerEnvConfig,
    KafkaWarpstreamIngestionProducerEnvConfig,
} from './cdp/outputs/producers'
import { IntegrationManagerService } from './cdp/services/managers/integration-manager.service'
import { EncryptedFields } from './cdp/utils/encryption-utils'

export * from '@posthog/node-common/types'
export type { CdpConfig } from './cdp/config'

export interface PluginsServerConfig
    extends CommonConfig,
        CdpConfig,
        KafkaWarpstreamIngestionProducerEnvConfig,
        KafkaWarpstreamCyclotronProducerEnvConfig,
        KafkaWarehouseProducerEnvConfig {}

export interface HubServices extends CommonHubServices {
    encryptedFields: EncryptedFields
    integrationManager: IntegrationManagerService
}

export interface Hub extends PluginsServerConfig, HubServices {}
