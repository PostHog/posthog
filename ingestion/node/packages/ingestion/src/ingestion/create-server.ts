import { PluginServerMode } from '@posthog/node-common/config'
import { NodeServer } from '@posthog/node-common/servers/base-server'

import { overrideConfigWithEnv } from '~/common/config/config'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { AiEventsServer } from '~/servers/ai-events-server'
import { ErrorTrackingServer } from '~/servers/error-tracking-server'
import { IngestionApiServer } from '~/servers/ingestion-api-server'
import { IngestionGeneralServer } from '~/servers/ingestion-general-server'
import { IngestionSessionReplayServer } from '~/servers/ingestion-session-replay-server'

/** The server for an ingestion mode, or null when the mode is not ingestion's. */
export function createIngestionServer(mode: PluginServerMode | null): NodeServer | null {
    switch (mode) {
        case PluginServerMode.ingestion_v2:
        case PluginServerMode.ingestion_v2_combined: {
            // The AI deployments still select their consumer by pipeline until charts moves them to the AI mode.
            const { INGESTION_PIPELINE } = overrideConfigWithEnv(getDefaultIngestionConsumerConfig())
            return INGESTION_PIPELINE === 'ai' ? new AiEventsServer() : new IngestionGeneralServer()
        }

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
            return null
    }
}
