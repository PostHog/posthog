import { getPluginServerCapabilities } from './capabilities'
import { defaultConfig } from './config/config'
import { initApp } from './init'
import { startPluginsServer } from './main/pluginsServer'

initApp(defaultConfig)
const capabilities = getPluginServerCapabilities(defaultConfig)
void startPluginsServer(defaultConfig, capabilities)
