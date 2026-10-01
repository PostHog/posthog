import { Message, TopicPartition, TopicPartitionOffset } from 'node-rdkafka'
import { Gauge } from 'prom-client'

import { parseKafkaHeaders } from '~/common/kafka/consumer/consumer-v1'

/**
 * Every record on an ML replay topic carries the Kafka timestamp of the replay record that its data
 * came from. Each lane compares its watermark on this one clock, so the minimum over the lanes on a
 * data path is how far back that data is complete in the training bucket.
 */
export const CAPTURE_TIMESTAMP_HEADER = 'capture-timestamp-ms'

/**
 * Events go through the mirror and the Parquet sink. Inline images go through the mirror and the
 * scrub lane. URL images go through the mirror, the fetch lane and the scrub lane.
 */
export type CapturedData = 'events' | 'event_metadata' | 'image_urls' | 'inline_images' | 'url_images'

export interface CapturedRecord {
    topic: string
    partition: number
    offset: number
    data: CapturedData
    capturedAtMs: number | undefined
}

export interface CaptureWatermarkRow {
    topic: string
    partition: number
    data: CapturedData
    capturedAtMs: number
}

export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

/**
 * The fetch lane sends a URL that a pass cannot finish to the end of its frontier partition, and the
 * scrub lane receives URL images in fetch order, not capture order. So a finished record does not
 * prove that the next records on the partition are newer. Finished records stay in the watermark for
 * this long, which lets a URL that comes back within the window keep the watermark down.
 */
const FINISHED_WINDOW_MS = 10 * 60 * 1000
/** Finished batches merge into one bucket per this span, so that a busy partition keeps a bounded number of buckets. */
const FINISHED_BUCKET_MS = 60 * 1000

interface HeldBatch {
    lastOffset: number
    earliestCapturedAtMs: number
}

interface FinishedBucket {
    startedAtMs: number
    lastFinishedAtMs: number
    earliestCapturedAtMs: number
}

interface DataWatermark {
    held: HeldBatch[]
    finished: FinishedBucket[]
    lastExpiredCapturedAtMs?: number
}

interface PartitionWatermarks {
    topic: string
    partition: number
    byData: Map<CapturedData, DataWatermark>
}

/** Read at scrape time by the gauge, which keeps the batch path free of gauge writes. */
const liveWatermarks = new Map<string, CaptureWatermark>()

// Never referenced again: constructing it registers it, and it pulls its own values at scrape time.
new Gauge({
    name: 'ml_replay_capture_watermark_timestamp_seconds',
    help: 'Unix time of the earliest capture among the records that this lane holds on the partition or finished in the last 10 minutes. The lane finished every record that it read with an earlier capture time. A record that the lane has not read yet can be older, for example a URL that the fetch lane sent back to the end of the frontier. The minimum over the lanes on a data path is how far back that data is complete',
    // No topic label, because the lanes' metric labels never carry a configured topic name. Each lane reads one topic.
    labelNames: ['partition', 'data'],
    collect() {
        const earliestByLabels = new Map<string, { partition: string; data: CapturedData; capturedAtMs: number }>()
        const nowMs = Date.now()
        for (const watermark of liveWatermarks.values()) {
            for (const row of watermark.snapshot(nowMs)) {
                const key = `${row.partition}\0${row.data}`
                const earliest = earliestByLabels.get(key)
                if (!earliest || row.capturedAtMs < earliest.capturedAtMs) {
                    earliestByLabels.set(key, {
                        partition: String(row.partition),
                        data: row.data,
                        capturedAtMs: row.capturedAtMs,
                    })
                }
            }
        }
        // Reset before setting, so that a partition that this pod gave up stops being reported from here.
        this.reset()
        for (const { partition, data, capturedAtMs } of earliestByLabels.values()) {
            this.labels({ partition, data }).set(capturedAtMs / 1000)
        }
    },
})

export class CaptureWatermark {
    private readonly partitions = new Map<string, PartitionWatermarks>()

    constructor(
        lane: string,
        private readonly finishedWindowMs = FINISHED_WINDOW_MS
    ) {
        liveWatermarks.set(lane, this)
    }

    /** Holds the capture time of each record until a stored offset passes it. */
    public hold(records: Iterable<CapturedRecord>): void {
        const batches = new Map<DataWatermark, HeldBatch>()
        for (const { topic, partition, offset, data, capturedAtMs } of records) {
            if (!isCaptureTimestamp(capturedAtMs)) {
                continue
            }
            const watermark = this.dataWatermark(topic, partition, data)
            const batch = batches.get(watermark)
            if (batch) {
                batch.lastOffset = Math.max(batch.lastOffset, offset)
                batch.earliestCapturedAtMs = Math.min(batch.earliestCapturedAtMs, capturedAtMs)
            } else {
                const held = { lastOffset: offset, earliestCapturedAtMs: capturedAtMs }
                batches.set(watermark, held)
                watermark.held.push(held)
            }
        }
    }

    /** `offsets` are what Kafka stores: the next offset to read on each partition. */
    public release(offsets: TopicPartitionOffset[], nowMs = Date.now()): void {
        for (const { topic, partition, offset } of offsets) {
            const watermarks = this.partitions.get(partitionKey(topic, partition))
            for (const watermark of watermarks?.byData.values() ?? []) {
                const stillHeld: HeldBatch[] = []
                for (const batch of watermark.held) {
                    if (batch.lastOffset < offset) {
                        this.finish(watermark, batch.earliestCapturedAtMs, nowMs)
                    } else {
                        stillHeld.push(batch)
                    }
                }
                watermark.held = stillHeld
            }
        }
    }

    /** Called on revoke, so that only the next owner of the partition reports it. */
    public forget(partitions: TopicPartition[]): void {
        for (const { topic, partition } of partitions) {
            this.partitions.delete(partitionKey(topic, partition))
        }
    }

    public snapshot(nowMs = Date.now()): CaptureWatermarkRow[] {
        const rows: CaptureWatermarkRow[] = []
        for (const { topic, partition, byData } of this.partitions.values()) {
            for (const [data, watermark] of byData) {
                this.expireFinished(watermark, nowMs)
                let earliestCapturedAtMs = Infinity
                for (const batch of watermark.held) {
                    earliestCapturedAtMs = Math.min(earliestCapturedAtMs, batch.earliestCapturedAtMs)
                }
                for (const bucket of watermark.finished) {
                    earliestCapturedAtMs = Math.min(earliestCapturedAtMs, bucket.earliestCapturedAtMs)
                }
                // A partition that stops delivering records keeps its last value instead of disappearing,
                // so that the minimum across partitions still includes a stalled consumer.
                const capturedAtMs = Number.isFinite(earliestCapturedAtMs)
                    ? earliestCapturedAtMs
                    : watermark.lastExpiredCapturedAtMs
                if (capturedAtMs !== undefined) {
                    rows.push({ topic, partition, data, capturedAtMs })
                }
            }
        }
        return rows
    }

    private finish(watermark: DataWatermark, earliestCapturedAtMs: number, nowMs: number): void {
        this.expireFinished(watermark, nowMs)
        const last = watermark.finished.at(-1)
        if (last && nowMs - last.startedAtMs < FINISHED_BUCKET_MS) {
            last.lastFinishedAtMs = nowMs
            last.earliestCapturedAtMs = Math.min(last.earliestCapturedAtMs, earliestCapturedAtMs)
        } else {
            watermark.finished.push({ startedAtMs: nowMs, lastFinishedAtMs: nowMs, earliestCapturedAtMs })
        }
    }

    private expireFinished(watermark: DataWatermark, nowMs: number): void {
        while (
            watermark.finished.length > 0 &&
            nowMs - watermark.finished[0].lastFinishedAtMs > this.finishedWindowMs
        ) {
            watermark.lastExpiredCapturedAtMs = watermark.finished.shift()!.earliestCapturedAtMs
        }
    }

    private dataWatermark(topic: string, partition: number, data: CapturedData): DataWatermark {
        const key = partitionKey(topic, partition)
        let watermarks = this.partitions.get(key)
        if (!watermarks) {
            watermarks = { topic, partition, byData: new Map() }
            this.partitions.set(key, watermarks)
        }
        let watermark = watermarks.byData.get(data)
        if (!watermark) {
            watermark = { held: [], finished: [] }
            watermarks.byData.set(data, watermark)
        }
        return watermark
    }
}

export function captureTimestampMs(message: Pick<Message, 'headers'>): number | undefined {
    const capturedAtMs = Number(parseKafkaHeaders(message.headers)[CAPTURE_TIMESTAMP_HEADER])
    return isCaptureTimestamp(capturedAtMs) ? capturedAtMs : undefined
}

export function capturedRecords(
    messages: Message[],
    dataOf: (message: Message) => CapturedData | undefined
): CapturedRecord[] {
    const records: CapturedRecord[] = []
    for (const message of messages) {
        const data = dataOf(message)
        if (data !== undefined) {
            records.push({
                topic: message.topic,
                partition: message.partition,
                offset: message.offset,
                data,
                capturedAtMs: captureTimestampMs(message),
            })
        }
    }
    return records
}

/** A refused store leaves the records to be read again, so the watermark moves only after Kafka accepts the offsets. */
export function releasingOffsetStore(store: OffsetStore, watermark: CaptureWatermark): OffsetStore {
    return {
        offsetsStore(offsets) {
            store.offsetsStore(offsets)
            watermark.release(offsets)
        },
    }
}

function isCaptureTimestamp(capturedAtMs: number | undefined): capturedAtMs is number {
    return capturedAtMs !== undefined && Number.isSafeInteger(capturedAtMs) && capturedAtMs > 0
}

function partitionKey(topic: string, partition: number): string {
    return `${topic}\0${partition}`
}
