// NOTE: Keep these as ~ imports as we can validate the build output this way
import { initTracing } from '~/common/tracing/otel'
import { PluginServer } from '~/server'
import { initSuperProperties } from '~/utils/posthog'

initSuperProperties()
initTracing()
const server = new PluginServer()
void server.start()
