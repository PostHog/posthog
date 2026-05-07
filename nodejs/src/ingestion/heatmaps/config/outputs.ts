import { HEATMAPS_OUTPUT, PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT } from '../../analytics/outputs'
import {
    APP_METRICS_OUTPUT,
    DLQ_OUTPUT,
    GROUPS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    OVERFLOW_OUTPUT,
} from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

/**
 * Register the outputs the heatmaps pipeline writes to.
 *
 * Simple register (topic + producer) — no dual-write surface. Heatmaps is a
 * new consumer with no active migration, so the dual-write knobs would just
 * be cost-free env-var noise.
 *
 * Note: `OVERFLOW_OUTPUT` is registered because `applyEventRestrictions` types
 * its redirect arm as `'overflow'`; the heatmaps pipeline pins `overflowEnabled`
 * to false so nothing is ever written to it. The topic config still has to
 * resolve to satisfy the type check.
 */
export function registerHeatmapsOutputs() {
    return new IngestionOutputsBuilder()
        .register(HEATMAPS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_HEATMAPS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_HEATMAPS_PRODUCER',
        })
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_DLQ_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_DLQ_PRODUCER',
        })
        .register(OVERFLOW_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_OVERFLOW_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_OVERFLOW_PRODUCER',
        })
        .register(GROUPS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_GROUPS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_GROUPS_PRODUCER',
        })
        .register(PERSONS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_PERSONS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_PERSONS_PRODUCER',
        })
        .register(PERSON_DISTINCT_IDS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER',
        })
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_APP_METRICS_PRODUCER',
        })
}
