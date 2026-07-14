import { Histogram, Meter, MetricOptions, metrics as metricsApi } from '@opentelemetry/api'

import { histogramWithExemplars } from '~/common/metrics/exemplars'
import { swallowing } from '~/common/metrics/swallow'

import { kafkaConsumerMessageAgeSeconds } from './metrics'

/**
 * OTLP-pushed twins of the consumer-loop prom metrics, plus the message-age (lag
 * in seconds) recorder that feeds both sinks. The prom side keeps feeding the
 * scrape/VictoriaMetrics dashboards; these land in the PostHog metrics product
 * through the exporter installed by initMetrics (common/metrics/otel-metrics.ts).
 *
 * Names and label sets deliberately match the prom metrics so dashboards translate 1:1.
 *
 * Instruments are acquired lazily on first record: the OTel metrics API has no proxy
 * provider, so instruments created at module load (before initMetrics runs) would be
 * bound to the noop meter forever.
 */

interface ConsumerInstruments {
    messageAge: Histogram
    batchSize: Histogram
    batchDuration: Histogram
    batchBackpressureDuration: Histogram
}

/** Keep in lockstep with the kafka_consumer_message_age_seconds prom buckets. */
export const MESSAGE_AGE_SECONDS_BOUNDARIES = [1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600]
/** Keep in lockstep with the consumer_batch_size prom buckets. */
const BATCH_SIZE_BOUNDARIES = [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000]
const BATCH_DURATION_MS_BOUNDARIES = [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000]

let instruments: ConsumerInstruments | null = null

const createHistogram = (meter: Meter, name: string, options?: MetricOptions): Histogram =>
    histogramWithExemplars(name, meter.createHistogram(name, options))

function getInstruments(): ConsumerInstruments {
    if (instruments === null) {
        const meter = metricsApi.getMeter('kafka-consumer')
        instruments = {
            messageAge: createHistogram(meter, 'kafka_consumer_message_age_seconds', {
                description: 'Age of the oldest message in each consumed batch — consumer lag in seconds',
                unit: 's',
                advice: { explicitBucketBoundaries: MESSAGE_AGE_SECONDS_BOUNDARIES },
            }),
            batchSize: createHistogram(meter, 'consumer_batch_size', {
                description: 'The size of the batches we are receiving from Kafka',
                advice: { explicitBucketBoundaries: BATCH_SIZE_BOUNDARIES },
            }),
            batchDuration: createHistogram(meter, 'consumed_batch_duration_ms', {
                description: 'Main loop consumer batch processing duration in ms',
                unit: 'ms',
                advice: { explicitBucketBoundaries: BATCH_DURATION_MS_BOUNDARIES },
            }),
            batchBackpressureDuration: createHistogram(meter, 'consumed_batch_backpressure_duration_ms', {
                description: 'Time spent waiting for background work to finish due to backpressure',
                unit: 'ms',
                advice: { explicitBucketBoundaries: BATCH_DURATION_MS_BOUNDARIES },
            }),
        }
    }
    return instruments
}

/**
 * Batch-level consume telemetry: batch size, and the age of the oldest message as the
 * consumer's lag-in-seconds signal. Age goes to BOTH sinks (the prom histogram and the
 * OTel twin); a batch with no broker timestamps records no age.
 */
export const recordBatchConsumed = swallowing(
    (topic: string, groupId: string, messages: ReadonlyArray<{ timestamp?: number }>, nowMs: number): void => {
        const { messageAge, batchSize } = getInstruments()
        batchSize.record(messages.length)

        let oldestTimestamp: number | undefined
        for (const message of messages) {
            if (
                message.timestamp !== undefined &&
                (oldestTimestamp === undefined || message.timestamp < oldestTimestamp)
            ) {
                oldestTimestamp = message.timestamp
            }
        }
        if (oldestTimestamp === undefined) {
            return
        }
        // Clamped: a producer clock slightly ahead of ours must not record negative age.
        const ageSeconds = Math.max(0, (nowMs - oldestTimestamp) / 1000)
        kafkaConsumerMessageAgeSeconds.labels(topic, groupId).observe(ageSeconds)
        messageAge.record(ageSeconds, { topic, groupId })
    }
)

export const recordConsumedBatchDuration = swallowing((durationMs: number, topic: string, groupId: string): void => {
    getInstruments().batchDuration.record(durationMs, { topic, groupId })
})

export const recordConsumedBatchBackpressure = swallowing(
    (durationMs: number, topic: string, groupId: string): void => {
        getInstruments().batchBackpressureDuration.record(durationMs, { topic, groupId })
    }
)

/** Test seam: forget cached instruments so a test-installed provider is picked up. */
export function resetConsumerOtelInstrumentsForTests(): void {
    instruments = null
}
