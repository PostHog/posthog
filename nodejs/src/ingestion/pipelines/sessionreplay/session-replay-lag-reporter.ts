import { Message, MessageHeader } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '~/common/metrics'

/** The message fields the reporter reads — a raw Kafka {@link Message} satisfies this structurally. */
export type LagReportableMessage = Pick<Message, 'partition' | 'headers'>

/**
 * Reports session replay ingestion lag — wall-clock time minus capture time (the `now` header set by
 * capture) — but only once a batch is durably flushed and its offsets committed, because that is when
 * replay data is actually ingested.
 *
 * The consumer records each poll batch's messages as they are processed and flushes the reporter after
 * the session batch flush succeeds. Only the capture timestamps (epoch ms) are retained per partition;
 * the messages themselves are never held.
 *
 * Unlike the per-event `record-ingestion-lag` step, which samples only events that were actually
 * ingested, this samples every consumed message — including ones the pipeline dropped or DLQ'd — because
 * it records the raw batch. That is intentional: dropped and DLQ'd messages still advance the committed
 * offset, so the metric reads as committed-offset progress versus capture time for the replay consumer.
 * On a flush failure with batch redelivery, retried messages can be sampled twice, consistent with the
 * consumer's existing batch-retry behavior.
 */
export class SessionReplayLagReporter {
    private pendingByPartition: Map<number, number[]> = new Map()

    constructor(private readonly topic: string) {}

    /** Extracts and stores the capture timestamp of each message that carries a valid `now` header. */
    public record(messages: LagReportableMessage[]): void {
        for (const message of messages) {
            const capturedAtMs = captureTimestampMs(message.headers)
            if (capturedAtMs === undefined) {
                continue
            }
            let pending = this.pendingByPartition.get(message.partition)
            if (pending === undefined) {
                pending = []
                this.pendingByPartition.set(message.partition, pending)
            }
            pending.push(capturedAtMs)
        }
    }

    /** Observes lag for every pending capture timestamp against a single now, then clears the state. */
    public flush(): void {
        const nowMs = Date.now()
        for (const [partition, timestamps] of this.pendingByPartition) {
            const partitionLabel = String(partition)
            for (const capturedAtMs of timestamps) {
                const lag = nowMs - capturedAtMs
                ingestionLagGauge.labels({ topic: this.topic, partition: partitionLabel }).set(lag)
                ingestionLagHistogram.labels({ partition: partitionLabel }).observe(lag)
            }
        }
        this.pendingByPartition.clear()
    }
}

/**
 * Parses just the `now` header to epoch ms, mirroring the capture-time parse in `parseEventHeaders`.
 * The pipeline already ran the full header parse (and its header-status metrics) on these messages, so
 * re-running it here would double-count those metrics; reading the one header we need avoids that.
 */
function captureTimestampMs(headers: MessageHeader[] | undefined): number | undefined {
    if (headers === undefined) {
        return undefined
    }
    for (const header of headers) {
        const value = header['now']
        if (value !== undefined) {
            const parsedMs = new Date(value.toString()).getTime()
            return isNaN(parsedMs) ? undefined : parsedMs
        }
    }
    return undefined
}
