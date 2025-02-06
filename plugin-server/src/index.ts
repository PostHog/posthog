import { getPluginServerCapabilities } from './capabilities'
import { defaultConfig } from './config/config'
import { startPluginsServer } from './main/pluginsServer'
import { initSentry } from './utils/sentry'

initSentry(defaultConfig)
const capabilities = getPluginServerCapabilities(defaultConfig)
void startPluginsServer(defaultConfig, capabilities)
