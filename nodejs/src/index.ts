// NOTE: Keep these as ~ imports as we can validate the build output this way
import { PluginServerMode } from '~/common/config'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { initMetrics } from '~/common/metrics/otel-metrics'
import { initTracing } from '~/common/tracing/otel'
import { initSuperProperties } from '~/common/utils/posthog'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { PluginServer } from '~/server'
import { NodeServer } from '~/servers/base-server'
import { ErrorTrackingServer } from '~/servers/error-tracking-server'
import { IngestionApiServer } from '~/servers/ingestion-api-server'
import { IngestionGeneralServer } from '~/servers/ingestion-general-server'
import { IngestionLogsServer } from '~/servers/ingestion-logs-server'
import { IngestionMetricsServer } from '~/servers/ingestion-metrics-server'
import { IngestionSessionReplayMlImageScrubServer } from '~/servers/ingestion-session-replay-ml-image-scrub-server'
import { IngestionSessionReplayMlMirrorServer } from '~/servers/ingestion-session-replay-ml-mirror-server'
import { IngestionSessionReplayMlParquetSinkServer } from '~/servers/ingestion-session-replay-ml-parquet-sink-server'
import { IngestionSessionReplayServer } from '~/servers/ingestion-session-replay-server'
import { IngestionTracesServer } from '~/servers/ingestion-traces-server'
import { RecordingApiServer } from '~/servers/recording-api-server'

function createServer(): NodeServer {
    const { PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE } = overrideConfigWithEnv(getDefaultIngestionConsumerConfig())
    initSuperProperties(PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE)

    switch (defaultConfig.PLUGIN_SERVER_MODE) {
        case PluginServerMode.ingestion_v2:
        case PluginServerMode.ingestion_v2_combined:
            return new IngestionGeneralServer()

        case PluginServerMode.ingestion_api:
            return new IngestionApiServer()

        case PluginServerMode.recordings_blob_ingestion_v2:
        case PluginServerMode.recordings_blob_ingestion_v2_overflow:
            return new IngestionSessionReplayServer()

        case PluginServerMode.recordings_blob_ingestion_v2_ml_mirror:
            return new IngestionSessionReplayMlMirrorServer()

        case PluginServerMode.recordings_blob_ingestion_v2_ml_parquet_sink:
            return new IngestionSessionReplayMlParquetSinkServer()

        case PluginServerMode.recordings_blob_ingestion_v2_ml_image_scrub:
            return new IngestionSessionReplayMlImageScrubServer()

        case PluginServerMode.recording_api:
            return new RecordingApiServer()

        case PluginServerMode.ingestion_error_tracking:
            return new ErrorTrackingServer()

        case PluginServerMode.ingestion_logs:
            return new IngestionLogsServer()

        case PluginServerMode.ingestion_metrics:
            return new IngestionMetricsServer()

        case PluginServerMode.ingestion_traces:
            return new IngestionTracesServer()

        default:
            // CDP modes, evaluation scheduler, local dev (null), local-cdp
            return new PluginServer()
    }
}

initTracing()
initMetrics()
const server = createServer()
void server.start()
