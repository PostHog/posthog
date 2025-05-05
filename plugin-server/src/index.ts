import { PluginServer } from './server'
import { initSuperProperties } from './utils/posthog'

initSuperProperties()
const server = new PluginServer()
void server.start()
