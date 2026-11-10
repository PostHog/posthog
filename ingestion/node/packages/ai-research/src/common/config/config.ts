import { getDefaultCommonConfig } from '@posthog/node-common/config'
import { overrideWithEnv } from '@posthog/node-common/config/config'
import { PluginsServerConfig } from '@posthog/node-common/types'

export { overrideConfigWithEnv } from '@posthog/node-common/config/config'

export const defaultConfig: PluginsServerConfig = overrideWithEnv(getDefaultCommonConfig())
