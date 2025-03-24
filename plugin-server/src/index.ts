import { defaultConfig } from './config/config'
import { PluginServer } from './server'
import { initSentry } from './utils/sentry'

initSentry(defaultConfig)
const server = new PluginServer()
void server.start()
