// NOTE: Keep these as ~ imports as we can validate the build output this way
import { PluginServer } from '~/src/server'
import { initSuperProperties } from '~/src/utils/posthog'

initSuperProperties()
const server = new PluginServer()
void server.start()
