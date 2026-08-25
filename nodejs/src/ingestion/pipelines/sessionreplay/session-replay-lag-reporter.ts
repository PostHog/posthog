import { Message, MessageHeader } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '~/common/metrics'

/** The message fields the reporter reads — a raw Kafka {@link Message} satisfies this structurally. */
export type LagReportableMessage = Pick<Message, 'partition' | 'headers'>

/**
 * Reports session replay ingestion lag — wall-clock time minus capture time (the `now` header set by
 * capture) — but only once a batch is durably flushed and its offsets committed, because that is when
 * replay data is actually ingested.
 *
 * The consumer records the recorded (OK-result) messages of each poll batch as they are processed and
 * flushes the reporter after the session batch flush succeeds. Only the capture timestamps (epoch ms)
 * are retained per partition; the messages themselves are never held.
 *
 * Only OK results are sampled — dropped, DLQ'd, and redirected messages are excluded — matching the
 * per-event `record-ingestion-lag` step's ingested-only semantics.
 *
 * A failed poll-batch flush crashes the process (eachBatch errors are uncaught), so its pending samples
 * die unreported and are re-read from the uncommitted offsets on restart. The one path that retains and
 * later reports is a failed or timed-out revoke-hook flush: it is swallowed and the partitions are given
 * up without committed offsets, so this still-running process can report its retained samples while the
 * new owner reprocesses the same messages — a bounded duplicate consistent with the at-least-once
 * delivery both owners already provide for the data itself.
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
 *
 * Kafka allows duplicate header keys, so this iterates every header and keeps the last valid `now` —
 * matching `parseEventHeaders`, so lag is reported from the same timestamp the message was processed
 * with. An invalid value does not clear a valid one seen earlier.
 */
function captureTimestampMs(headers: MessageHeader[] | undefined): number | undefined {
    if (headers === undefined) {
        return undefined
    }
    let capturedAtMs: number | undefined
    for (const header of headers) {
        const value = header['now']
        if (value !== undefined) {
            const parsedMs = new Date(value.toString()).getTime()
            if (!isNaN(parsedMs)) {
                capturedAtMs = parsedMs
            }
        }
    }
    return capturedAtMs
}
