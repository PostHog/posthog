// NOTE: Keep these as ~ imports as we can validate the build output this way
import { PluginServerMode } from '~/common/config'
import { initTracing } from '~/common/tracing/otel'
import { defaultConfig } from '~/config/config'
import { PluginServer } from '~/server'
import { NodeServer } from '~/servers/base-server'
import { ErrorTrackingServer } from '~/servers/error-tracking-server'
import { IngestionGeneralServer } from '~/servers/ingestion-general-server'
import { initSuperProperties } from '~/utils/posthog'

function createServer(): NodeServer {
    switch (defaultConfig.PLUGIN_SERVER_MODE) {
        case PluginServerMode.ingestion_v2:
        case PluginServerMode.ingestion_v2_testing:
        case PluginServerMode.ingestion_v2_combined:
            return new IngestionGeneralServer()

        case PluginServerMode.ingestion_error_tracking:
            return new ErrorTrackingServer()

        default:
            // CDP modes, logs, evaluation scheduler, recordings, local dev (null), local-cdp
            return new PluginServer()
    }
}

initSuperProperties()
initTracing()
const server = createServer()
void server.start()
