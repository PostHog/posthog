import { PluginServerMode } from '@posthog/node-common/config'
import { initMetrics } from '@posthog/node-common/metrics/otel-metrics'
import { NodeServer } from '@posthog/node-common/servers/base-server'
import { initTracing } from '@posthog/node-common/tracing/otel'
import { initSuperProperties } from '@posthog/node-common/utils/posthog'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { AiEventsServer } from '~/servers/ai-events-server'
import {
    AiResearchV4ImageFetchRetryServer,
    AiResearchV4ImageFetchServer,
} from '~/servers/ai-research-v4-image-fetch-server'
import { AiResearchV4ParquetSinkServer } from '~/servers/ai-research-v4-parquet-sink-server'
import { ErrorTrackingServer } from '~/servers/error-tracking-server'
import { IngestionApiServer } from '~/servers/ingestion-api-server'
import { IngestionGeneralServer } from '~/servers/ingestion-general-server'
import { IngestionMetricsServer } from '~/servers/ingestion-metrics-server'
import { IngestionSessionReplayMlImageFetchRetryServer } from '~/servers/ingestion-session-replay-ml-image-fetch-retry-server'
import { IngestionSessionReplayMlImageFetchServer } from '~/servers/ingestion-session-replay-ml-image-fetch-server'
import { IngestionSessionReplayMlImageScrubDlqReplayServer } from '~/servers/ingestion-session-replay-ml-image-scrub-dlq-replay-server'
import { IngestionSessionReplayMlImageScrubServer } from '~/servers/ingestion-session-replay-ml-image-scrub-server'
import { IngestionSessionReplayMlMirrorServer } from '~/servers/ingestion-session-replay-ml-mirror-server'
import { IngestionSessionReplayMlParquetSinkServer } from '~/servers/ingestion-session-replay-ml-parquet-sink-server'
import { IngestionSessionReplayServer } from '~/servers/ingestion-session-replay-server'

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

        case PluginServerMode.recordings_blob_ingestion_v2_ml_image_scrub_dlq_replay:
            return new IngestionSessionReplayMlImageScrubDlqReplayServer()

        case PluginServerMode.recordings_blob_ingestion_v2_ml_image_fetch:
            return new IngestionSessionReplayMlImageFetchServer()

        case PluginServerMode.recordings_blob_ingestion_v2_ml_image_fetch_retry:
            return new IngestionSessionReplayMlImageFetchRetryServer()

        case PluginServerMode.ai_research_v4_image_fetch:
            return new AiResearchV4ImageFetchServer()

        case PluginServerMode.ai_research_v4_image_fetch_retry:
            return new AiResearchV4ImageFetchRetryServer()

        case PluginServerMode.ai_research_v4_parquet_sink:
            return new AiResearchV4ParquetSinkServer()

        case PluginServerMode.ingestion_error_tracking:
            return new ErrorTrackingServer()

        case PluginServerMode.ingestion_ai:
            return new AiEventsServer()

        case PluginServerMode.ingestion_metrics:
            return new IngestionMetricsServer()

        default:
            throw new Error(`PLUGIN_SERVER_MODE ${defaultConfig.PLUGIN_SERVER_MODE} is not an ingestion mode`)
    }
}

initTracing()
initMetrics()
const server = createServer()
void server.start()
