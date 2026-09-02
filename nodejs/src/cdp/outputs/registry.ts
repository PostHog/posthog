import {
    APP_METRICS_OUTPUT,
    HOG_INVOCATION_RESULTS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    MESSAGE_ASSETS_OUTPUT,
} from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'

import { WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT } from './outputs'

/**
 * Outputs the CDP deployments write to. Each output's topic + producer are
 * env-controlled so the route can be flipped between MSK / Warpstream /
 * default / warehouse clusters without code changes.
 *
 * - `APP_METRICS_OUTPUT` + `LOG_ENTRIES_OUTPUT` — hog function monitoring path
 *   (also used for legacy plugin app metrics since they share the
 *   `clickhouse_app_metrics2` schema).
 * - `WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT` — warehouse source webhook payloads.
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
        .register(HOG_INVOCATION_RESULTS_OUTPUT, {
            topicKey: 'HOG_INVOCATION_RESULTS_TOPIC',
            producerKey: 'HOG_INVOCATION_RESULTS_PRODUCER',
        })
        .register(MESSAGE_ASSETS_OUTPUT, {
            topicKey: 'MESSAGE_ASSETS_TOPIC',
            producerKey: 'MESSAGE_ASSETS_PRODUCER',
        })
        .register(WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT, {
            topicKey: 'CDP_WAREHOUSE_SOURCE_WEBHOOKS_TOPIC',
            producerKey: 'CDP_WAREHOUSE_SOURCE_WEBHOOKS_PRODUCER',
        })
}
