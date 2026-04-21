import { INGESTION_LAG_INDICATOR } from '.'

import { INGESTION_LATENCY_GROUP } from '../../common/slas'
import { IngestionSlaBuilder } from '../../slas/builder'

/**
 * Analytics ingestion SLAs.
 *
 * Call `.build({ pipeline, lane })` at service startup to materialize metrics.
 */
export function createSlaRegistry() {
    return new IngestionSlaBuilder().group(INGESTION_LATENCY_GROUP, (latency) =>
        latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
            ingestionLag
                .objective('under_10s', { thresholdMs: 10000, targetRatio: 0.9 })
                .objective('under_30s', { thresholdMs: 30000, targetRatio: 0.995 })
                .agreement('under_60s', { thresholdMs: 60000, targetRatio: 0.9999 })
        )
    )
}
