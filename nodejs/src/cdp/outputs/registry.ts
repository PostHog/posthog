import { APP_METRICS_OUTPUT, LOG_ENTRIES_OUTPUT } from '../../ingestion/common/outputs'
import { IngestionOutputsBuilder } from '../../ingestion/outputs/ingestion-outputs-builder'

/**
 * Outputs the CDP monitoring path writes to. Each output's topic + producer
 * are env-controlled via `HOG_FUNCTION_MONITORING_*_TOPIC` and
 * `HOG_FUNCTION_MONITORING_*_PRODUCER`.
 */
export function createCdpOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC',
            producerKey: 'HOG_FUNCTION_MONITORING_APP_METRICS_PRODUCER',
        })
        .register(LOG_ENTRIES_OUTPUT, {
            topicKey: 'HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC',
            producerKey: 'HOG_FUNCTION_MONITORING_LOG_ENTRIES_PRODUCER',
        })
}
