import { APP_METRICS_OUTPUT, HOG_INVOCATION_RESULTS_OUTPUT, LOG_ENTRIES_OUTPUT } from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'

import {
    PRECALCULATED_PERSON_PROPERTIES_OUTPUT,
    PREFILTERED_EVENTS_OUTPUT,
    WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT,
} from './outputs'

/**
 * Outputs the CDP deployments write to. Each output's topic + producer are
 * env-controlled so the route can be flipped between MSK / Warpstream /
 * default / warehouse clusters without code changes.
 *
 * - `APP_METRICS_OUTPUT` + `LOG_ENTRIES_OUTPUT` — hog function monitoring path
 *   (also used for legacy plugin app metrics since they share the
 *   `clickhouse_app_metrics2` schema).
 * - `PREFILTERED_EVENTS_OUTPUT` + `PRECALCULATED_PERSON_PROPERTIES_OUTPUT` —
 *   precalculated-filters consumer writes to ClickHouse.
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
        .register(PREFILTERED_EVENTS_OUTPUT, {
            topicKey: 'CDP_PREFILTERED_EVENTS_TOPIC',
            producerKey: 'CDP_PREFILTERED_EVENTS_PRODUCER',
        })
        .register(PRECALCULATED_PERSON_PROPERTIES_OUTPUT, {
            topicKey: 'CDP_PRECALCULATED_PERSON_PROPERTIES_TOPIC',
            producerKey: 'CDP_PRECALCULATED_PERSON_PROPERTIES_PRODUCER',
        })
        .register(WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT, {
            topicKey: 'CDP_WAREHOUSE_SOURCE_WEBHOOKS_TOPIC',
            producerKey: 'CDP_WAREHOUSE_SOURCE_WEBHOOKS_PRODUCER',
        })
}
