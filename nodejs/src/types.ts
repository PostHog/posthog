import type { CdpConfig } from '@posthog/hog-engine/cdp/config'
import type {
    KafkaWarehouseProducerEnvConfig,
    KafkaWarpstreamCyclotronProducerEnvConfig,
    KafkaWarpstreamIngestionProducerEnvConfig,
} from '@posthog/hog-engine/cdp/outputs/producers'
import { IntegrationManagerService } from '@posthog/hog-engine/cdp/services/managers/integration-manager.service'
import { EncryptedFields } from '@posthog/hog-engine/cdp/utils/encryption-utils'
import type { PersonServices } from '@posthog/ingestion-common/types'
import type { CommonConfig, HubServices as CommonHubServices } from '@posthog/node-common/types'

import type { LogsIngestionConsumerConfig, TracesIngestionConsumerConfig } from '~/logs/config'

import type { AIObservabilityConfig } from './ai-observability/config'

export * from '@posthog/node-common/types'

// Re-export config types from domain-specific files, this is to avoid mass refactors, we can eventually update it
export type { CdpConfig } from '@posthog/hog-engine/cdp/config'
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

export interface HubServices extends CommonHubServices, PersonServices {
    encryptedFields: EncryptedFields
    integrationManager: IntegrationManagerService
}

export interface Hub extends PluginsServerConfig, HubServices {}
