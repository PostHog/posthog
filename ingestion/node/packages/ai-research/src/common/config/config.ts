import { getDefaultCommonConfig } from '@posthog/node-common/config'
import { overrideWithEnv } from '@posthog/node-common/config/config'
import {
    InternalLogsProducerConfig,
    getDefaultInternalLogsProducerConfig,
} from '@posthog/node-common/logs/internal-logs-producer'
import { PluginsServerConfig as CommonPluginsServerConfig } from '@posthog/node-common/types'

export { overrideConfigWithEnv } from '@posthog/node-common/config/config'

// The replay server config these services build on carries the internal logs producer settings
// and CDP's switch list for it; these lanes send no internal logs, so the list stays empty.
export type PluginsServerConfig = CommonPluginsServerConfig &
    InternalLogsProducerConfig & { CDP_INTERNAL_LOGS_SOURCES: string }

export const defaultConfig: PluginsServerConfig = overrideWithEnv({
    ...getDefaultCommonConfig(),
    ...getDefaultInternalLogsProducerConfig(),
    CDP_INTERNAL_LOGS_SOURCES: '',
})
