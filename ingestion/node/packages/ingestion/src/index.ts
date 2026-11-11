import { initMetrics } from '@posthog/node-common/metrics/otel-metrics'
import { initTracing } from '@posthog/node-common/tracing/otel'
import { initSuperProperties } from '@posthog/node-common/utils/posthog'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { createIngestionServer } from '~/ingestion/create-server'

initTracing()
initMetrics()
const { PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE } = overrideConfigWithEnv(getDefaultIngestionConsumerConfig())
initSuperProperties(PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE)
const server = createIngestionServer(defaultConfig.PLUGIN_SERVER_MODE)
if (!server) {
    throw new Error(`PLUGIN_SERVER_MODE ${defaultConfig.PLUGIN_SERVER_MODE} is not an ingestion mode`)
}
void server.start()
