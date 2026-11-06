import type { CommonConfig, HubServices as CommonHubServices } from '@posthog/node-common/types'

import type { LogsIngestionConsumerConfig, TracesIngestionConsumerConfig } from '~/logs/config'

import type { AIObservabilityConfig } from './ai-observability/config'
import type { CdpConfig } from './cdp/config'
import type {
    KafkaWarehouseProducerEnvConfig,
    KafkaWarpstreamCyclotronProducerEnvConfig,
    KafkaWarpstreamIngestionProducerEnvConfig,
} from './cdp/outputs/producers'
import { IntegrationManagerService } from './cdp/services/managers/integration-manager.service'
import { EncryptedFields } from './cdp/utils/encryption-utils'

// The shared domain types; the settings merge and the hub below are this service's own.
export * from '@posthog/node-common/types'

// Re-export config types from domain-specific files, this is to avoid mass refactors, we can eventually update it
export type { CdpConfig } from './cdp/config'
export type { AIObservabilityConfig } from './ai-observability/config'
export type { LogsIngestionConsumerConfig } from '~/logs/config'

export interface PluginsServerConfig
    extends CommonConfig,
        CdpConfig,
        AIObservabilityConfig,
        LogsIngestionConsumerConfig,
        TracesIngestionConsumerConfig,
        // Producer envs needed by the CDP producer registry the legacy big server builds.
        KafkaWarpstreamIngestionProducerEnvConfig,
        KafkaWarpstreamCyclotronProducerEnvConfig,
        KafkaWarehouseProducerEnvConfig {}

export interface HubServices extends CommonHubServices {
    encryptedFields: EncryptedFields
    integrationManager: IntegrationManagerService
}

export interface Hub extends PluginsServerConfig, HubServices {}
