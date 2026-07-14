import { Gauge, metrics as metricsApi } from '@opentelemetry/api'

import { swallowing } from '~/common/metrics/swallow'

/**
 * OTLP-pushed twins of the producer-queue prom gauges set by ProducerStatsTracker.
 * A growing produce queue is the earliest backpressure signal when downstream Kafka
 * slows, so these need to be visible in the PostHog metrics product during incidents.
 *
 * Names and label sets deliberately match the prom gauges so dashboards translate 1:1.
 *
 * Instruments are acquired lazily on first record: the OTel metrics API has no proxy
 * provider, so instruments created at module load (before initMetrics runs) would be
 * bound to the noop meter forever.
 */

interface ProducerInstruments {
    queueMessages: Gauge
    queueBytes: Gauge
    anyBrokersDown: Gauge
}

let instruments: ProducerInstruments | null = null

function getInstruments(): ProducerInstruments {
    if (instruments === null) {
        const meter = metricsApi.getMeter('kafka-producer')
        instruments = {
            queueMessages: meter.createGauge('kafka_producer_queue_messages', {
                description: 'Current number of messages in the producer queue.',
            }),
            queueBytes: meter.createGauge('kafka_producer_queue_bytes', {
                description: 'Current size in bytes of messages in the producer queue.',
                unit: 'By',
            }),
            anyBrokersDown: meter.createGauge('kafka_producer_any_brokers_down', {
                description: '1 if any broker the producer knows about is not in the UP state, 0 otherwise.',
            }),
        }
    }
    return instruments
}

export const recordProducerQueueStats = swallowing(
    (producerName: string, stats: { queueMessages?: number; queueBytes?: number; anyBrokersDown?: boolean }): void => {
        const { queueMessages, queueBytes, anyBrokersDown } = getInstruments()
        const attributes = { producer_name: producerName }
        if (stats.queueMessages !== undefined) {
            queueMessages.record(stats.queueMessages, attributes)
        }
        if (stats.queueBytes !== undefined) {
            queueBytes.record(stats.queueBytes, attributes)
        }
        if (stats.anyBrokersDown !== undefined) {
            anyBrokersDown.record(stats.anyBrokersDown ? 1 : 0, attributes)
        }
    }
)

/** Test seam: forget cached instruments so a test-installed provider is picked up. */
export function resetProducerOtelInstrumentsForTests(): void {
    instruments = null
}
