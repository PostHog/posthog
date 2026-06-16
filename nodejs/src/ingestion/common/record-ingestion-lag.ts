import { Message } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '../../common/metrics'
import { EventHeaders } from '../../types'

/**
 * Records ingestion lag for an event whose emission has just been acked by
 * Kafka, computed from the capture time (`now` header). No sample is recorded
 * when the capture time is missing.
 *
 * Call this from the ack callback (`.then`) of a terminal, emitting step so the
 * lag reflects capture time to the moment Kafka acknowledged the produce, not
 * processing time.
 *
 * Pipeline and lane identity come from the registry-wide default labels
 * (`ingestion_pipeline`, `ingestion_lane`), so the metrics only carry
 * topic/partition labels.
 */
export function recordIngestionLag(headers: EventHeaders, message: Message): void {
    if (headers.now === undefined) {
        return
    }

    const lag = Date.now() - headers.now.getTime()
    const partition = String(message.partition)
    ingestionLagGauge.labels({ topic: message.topic, partition }).set(lag)
    ingestionLagHistogram.labels({ partition }).observe(lag)
}
