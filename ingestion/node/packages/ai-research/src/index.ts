import { PluginServerMode } from '@posthog/node-common/config'
import { initMetrics } from '@posthog/node-common/metrics/otel-metrics'
import { NodeServer } from '@posthog/node-common/servers/base-server'
import { initTracing } from '@posthog/node-common/tracing/otel'

import { defaultConfig } from '~/common/config/config'
import {
    AiResearchV4ImageFetchRetryServer,
    AiResearchV4ImageFetchServer,
} from '~/servers/ai-research-v4-image-fetch-server'
import { AiResearchV4ParquetSinkServer } from '~/servers/ai-research-v4-parquet-sink-server'
import { IngestionSessionReplayMlImageFetchRetryServer } from '~/servers/ingestion-session-replay-ml-image-fetch-retry-server'
import { IngestionSessionReplayMlImageFetchServer } from '~/servers/ingestion-session-replay-ml-image-fetch-server'
import { IngestionSessionReplayMlImageScrubDlqReplayServer } from '~/servers/ingestion-session-replay-ml-image-scrub-dlq-replay-server'
import { IngestionSessionReplayMlImageScrubServer } from '~/servers/ingestion-session-replay-ml-image-scrub-server'
import { IngestionSessionReplayMlMirrorServer } from '~/servers/ingestion-session-replay-ml-mirror-server'
import { IngestionSessionReplayMlParquetSinkServer } from '~/servers/ingestion-session-replay-ml-parquet-sink-server'

function createServer(): NodeServer {
    switch (defaultConfig.PLUGIN_SERVER_MODE) {
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

        default:
            throw new Error(`PLUGIN_SERVER_MODE ${defaultConfig.PLUGIN_SERVER_MODE} is not an AI research mode`)
    }
}

initTracing()
initMetrics()
const server = createServer()
void server.start()
