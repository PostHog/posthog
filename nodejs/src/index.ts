// NOTE: Keep these as ~ imports as we can validate the build output this way
import { PluginServerMode } from '@posthog/node-common/config'
import { initMetrics } from '@posthog/node-common/metrics/otel-metrics'
import { NodeServer } from '@posthog/node-common/servers/base-server'
import { initTracing } from '@posthog/node-common/tracing/otel'

import { defaultConfig } from '~/common/config/config'
import { PluginServer } from '~/server'
import { IngestionLogsServer } from '~/servers/ingestion-logs-server'
import { IngestionMetricsServer } from '~/servers/ingestion-metrics-server'
import { IngestionTracesServer } from '~/servers/ingestion-traces-server'
import { PushApiServer } from '~/servers/push-api-server'
import { RecordingApiServer } from '~/servers/recording-api-server'

// The event, session replay, error tracking, metrics and AI research modes run from @posthog/ingestion.
function createServer(): NodeServer {
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
const server = createServer()
void server.start()
