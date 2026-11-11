// NOTE: Keep these as ~ imports as we can validate the build output this way
import { createIngestionServer } from '@posthog/ingestion/create-server'
import { PluginServerMode } from '@posthog/node-common/config'
import { initMetrics } from '@posthog/node-common/metrics/otel-metrics'
import { NodeServer } from '@posthog/node-common/servers/base-server'
import { initTracing } from '@posthog/node-common/tracing/otel'
import { initSuperProperties } from '@posthog/node-common/utils/posthog'

import { defaultConfig } from '~/common/config/config'
import { PluginServer } from '~/server'
import { IngestionLogsServer } from '~/servers/ingestion-logs-server'
import { IngestionMetricsServer } from '~/servers/ingestion-metrics-server'
import { IngestionTracesServer } from '~/servers/ingestion-traces-server'
import { PushApiServer } from '~/servers/push-api-server'
import { RecordingApiServer } from '~/servers/recording-api-server'

function createServer(): NodeServer {
    // This image keeps running the ingestion modes until charts moves those deployments to ingestion-node.
    const ingestionServer = createIngestionServer(defaultConfig.PLUGIN_SERVER_MODE)
    if (ingestionServer) {
        return ingestionServer
    }

    switch (defaultConfig.PLUGIN_SERVER_MODE) {
        case PluginServerMode.recording_api:
            return new RecordingApiServer()

        case PluginServerMode.ingestion_logs:
            return new IngestionLogsServer()

        case PluginServerMode.ingestion_metrics:
            return new IngestionMetricsServer()

        case PluginServerMode.ingestion_traces:
            return new IngestionTracesServer()

        case PluginServerMode.push_api:
            return new PushApiServer()

        default:
            // CDP modes, evaluation scheduler, local dev (null), local-cdp
            return new PluginServer()
    }
}

initTracing()
initMetrics()
initSuperProperties()
const server = createServer()
void server.start()
