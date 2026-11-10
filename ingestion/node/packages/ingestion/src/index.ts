import { PluginServerMode } from '@posthog/node-common/config'
import { initMetrics } from '@posthog/node-common/metrics/otel-metrics'
import { NodeServer } from '@posthog/node-common/servers/base-server'
import { initTracing } from '@posthog/node-common/tracing/otel'
import { initSuperProperties } from '@posthog/node-common/utils/posthog'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { AiEventsServer } from '~/servers/ai-events-server'
import { ErrorTrackingServer } from '~/servers/error-tracking-server'
import { IngestionApiServer } from '~/servers/ingestion-api-server'
import { IngestionGeneralServer } from '~/servers/ingestion-general-server'
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

        case PluginServerMode.ingestion_error_tracking:
            return new ErrorTrackingServer()

        case PluginServerMode.ingestion_ai:
            return new AiEventsServer()

        default:
            throw new Error(`PLUGIN_SERVER_MODE ${defaultConfig.PLUGIN_SERVER_MODE} is not an ingestion mode`)
    }
}

initTracing()
initMetrics()
const server = createServer()
void server.start()
