// NOTE: Keep these as ~ imports as we can validate the build output this way
import { PluginServer } from '~/server'
import { initSuperProperties } from '~/utils/posthog'

initSuperProperties()
const server = new PluginServer()
void server.start()
