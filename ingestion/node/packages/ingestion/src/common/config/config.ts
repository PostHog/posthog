import { getDefaultCdpConfig } from '@posthog/hog-engine/cdp/config'
import { getDefaultCommonConfig } from '@posthog/node-common/config'
import { overrideWithEnv } from '@posthog/node-common/config/config'
import { getDefaultInternalLogsProducerConfig } from '@posthog/node-common/logs/internal-logs-producer'

import { PluginsServerConfig } from '~/types'

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
        ...getDefaultInternalLogsProducerConfig(),
        CDP_INTERNAL_LOGS_SOURCES: getDefaultCdpConfig().CDP_INTERNAL_LOGS_SOURCES,
    }
}
