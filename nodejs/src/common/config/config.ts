import { getDefaultCdpConfig } from '@posthog/hog-engine/cdp/config'
import {
    getDefaultKafkaWarehouseProducerEnvConfig,
    getDefaultKafkaWarpstreamCyclotronProducerEnvConfig,
    getDefaultKafkaWarpstreamIngestionProducerEnvConfig,
} from '@posthog/hog-engine/cdp/outputs/producers'
import { getDefaultCommonConfig } from '@posthog/node-common/config'
import { overrideWithEnv } from '@posthog/node-common/config/config'

import { getDefaultAIObservabilityConfig } from '~/ai-observability/config'
import { getDefaultLogsIngestionConsumerConfig, getDefaultTracesIngestionConsumerConfig } from '~/logs/config'
import { PluginsServerConfig } from '~/types'

// Re-export for backwards compatibility
export { DEFAULT_HTTP_SERVER_PORT } from '@posthog/node-common/config'
export {
    buildIntegerMatcher,
    buildIntegerMatcherWithPercentage,
    buildStringMatcher,
    overrideConfigWithEnv,
    overrideWithEnv,
} from '@posthog/node-common/config/config'

export const defaultConfig = overrideWithEnv(getDefaultConfig())

export function getDefaultConfig(): PluginsServerConfig {
    return {
        ...getDefaultCommonConfig(),
        ...getDefaultCdpConfig(),
        ...getDefaultAIObservabilityConfig(),
        ...getDefaultLogsIngestionConsumerConfig(),
        ...getDefaultTracesIngestionConsumerConfig(),
        ...getDefaultKafkaWarpstreamIngestionProducerEnvConfig(),
        ...getDefaultKafkaWarpstreamCyclotronProducerEnvConfig(),
        ...getDefaultKafkaWarehouseProducerEnvConfig(),
    }
}
