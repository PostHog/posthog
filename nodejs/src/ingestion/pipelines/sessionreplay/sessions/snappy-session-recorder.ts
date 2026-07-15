import { DateTime } from 'luxon'
import snappy from 'snappy'

import { logger } from '~/common/utils/logger'
import {
    PRE_SERIALIZED_FLAG_ACTIVE,
    PRE_SERIALIZED_FLAG_CLICK,
    PRE_SERIALIZED_FLAG_KEYPRESS,
    PRE_SERIALIZED_FLAG_MOUSE_ACTIVITY,
    ParsedMessageData,
} from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { hrefFrom, isClick, isKeypress, isMouseActivity } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import {
    SegmentationEvent,
    activeMillisecondsFromSegmentationEvents,
    toSegmentationEvent,
} from '~/ingestion/pipelines/sessionreplay/segmentation'

const MAX_SNAPSHOT_FIELD_LENGTH = 1000
const MAX_URL_LENGTH = 4 * 1024 // 4KB
const MAX_URLS_COUNT = 25

/**
 * Per-message session data, precomputed by the serialize reduce step (business logic): the
 * serialized JSONL chunks plus everything the session block aggregates per message. Pure data —
 * the recorder folds it into session state without looking at the raw events again.
 */
export interface SerializedSessionData {
    /** Serialized JSONL chunks of `[windowId, event]` lines. */
    chunks: Buffer[]
    /** Raw bytes across the chunks (before compression). */
    rawBytes: number
    eventCount: number
    segmentationEvents: SegmentationEvent[]
    /** Hrefs seen, in event order — may repeat; the recorder dedupes, truncates, and caps. */
    urls: string[]
    clickCount: number
    keypressCount: number
    mouseActivityCount: number
    eventsRange: { start: DateTime; end: DateTime }
    distinctId: string
    snapshotSource: string
    snapshotLibrary: string | null
}

/**
 * Serializes one parsed message into the per-message session data the recorder aggregates:
 * the JSONL block chunks plus the counts, urls, and segmentation events derived from the events.
 * Handles both parsed events and the native anonymizer's pre-serialized fast path.
 */
export function serializeSessionData(message: ParsedMessageData): SerializedSessionData {
    const base = {
        eventsRange: { start: message.eventsRange.start, end: message.eventsRange.end },
        distinctId: message.distinct_id,
        snapshotSource: (message.snapshot_source || 'web').slice(0, MAX_SNAPSHOT_FIELD_LENGTH),
        snapshotLibrary: message.snapshot_library ? message.snapshot_library.slice(0, MAX_SNAPSHOT_FIELD_LENGTH) : null,
    }

    if (message.preSerialized) {
        // The native anonymizer already serialized the block lines; the counts, segmentation, and
        // urls come from the per-event metadata instead of walking parsed events.
        const { lines, events } = message.preSerialized
        const segmentationEvents: SegmentationEvent[] = []
        const urls: string[] = []
        let clickCount = 0
        let keypressCount = 0
        let mouseActivityCount = 0
        for (const event of events) {
            segmentationEvents.push({
                timestamp: event.ts,
                isActive: (event.flags & PRE_SERIALIZED_FLAG_ACTIVE) !== 0,
            })
            if (event.href) {
                urls.push(event.href)
            }
            if (event.flags & PRE_SERIALIZED_FLAG_CLICK) {
                clickCount += 1
            }
            if (event.flags & PRE_SERIALIZED_FLAG_KEYPRESS) {
                keypressCount += 1
            }
            if (event.flags & PRE_SERIALIZED_FLAG_MOUSE_ACTIVITY) {
                mouseActivityCount += 1
            }
        }
        return {
            ...base,
            chunks: [lines],
            rawBytes: lines.length,
            eventCount: events.length,
            segmentationEvents,
            urls,
            clickCount,
            keypressCount,
            mouseActivityCount,
        }
    }

    const chunks: Buffer[] = []
    const segmentationEvents: SegmentationEvent[] = []
    const urls: string[] = []
    let rawBytes = 0
    let eventCount = 0
    let clickCount = 0
    let keypressCount = 0
    let mouseActivityCount = 0
    for (const [windowId, events] of Object.entries(message.eventsByWindowId)) {
        for (const event of events) {
            const serializedLine = JSON.stringify([windowId, event]) + '\n'
            const chunk = Buffer.from(serializedLine)
            chunks.push(chunk)
            rawBytes += chunk.length

            segmentationEvents.push(toSegmentationEvent(event))

            const eventUrl = hrefFrom(event)
            if (eventUrl) {
                urls.push(eventUrl)
            }
            if (isClick(event)) {
                clickCount += 1
            }
            if (isKeypress(event)) {
                keypressCount += 1
            }
            if (isMouseActivity(event)) {
                mouseActivityCount += 1
            }
            eventCount++
        }
    }
    return {
        ...base,
        chunks,
        rawBytes,
        eventCount,
        segmentationEvents,
        urls,
        clickCount,
        keypressCount,
        mouseActivityCount,
    }
}

export interface EndResult {
    /** The complete compressed session block */
    buffer: Buffer
    /** Number of events in the session block */
    eventCount: number
    /** Timestamp of the first event in the session block */
    startDateTime: DateTime
    /** Timestamp of the last event in the session block */
    endDateTime: DateTime
    /** First URL of the session */
    firstUrl: string | null
    /** All URLs visited in the session */
    urls: string[]
    /** Number of clicks in the session */
    clickCount: number
    /** Number of keypresses in the session */
    keypressCount: number
    /** Number of mouse activity events in the session */
    mouseActivityCount: number
    /** Active time in milliseconds */
    activeMilliseconds: number
    /** Size of the session data in bytes */
    size: number
    /** Number of messages in the session */
    messageCount: number
    /** Source of the snapshot (Web/Mobile) */
    snapshotSource: string | null
    /** Library used for the snapshot */
    snapshotLibrary: string | null
    /** ID of the batch this session belongs to */
    batchId: string
}

/**
 * Records events for a single session recording using Snappy compression
 *
 * Buffers events and provides them as a snappy-compressed session recording block that can be
 * stored in a session batch file. The session recording block can be read as an independent unit.
 *
 * ```
 * Session Batch File
 * ├── Snappy Session Recording Block 1 <── One SessionRecorder corresponds to one block
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       ├── [windowId, event2]
 * │       └── ...
 * ├── Snappy Session Recording Block 2
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       └── ...
 * └── ...
 * ```
 *
 * The session block format (after decompression) is a sequence of newline-delimited JSON records.
 * Each record is an array of [windowId, event].
 */
export class SnappySessionRecorder {
    private readonly uncompressedChunks: Buffer[] = []
    private eventCount: number = 0
    private size: number = 0
    private ended = false
    private startDateTime: DateTime | null = null
    private endDateTime: DateTime | null = null
    private _distinctId: string | null = null
    private urls: Set<string> = new Set()
    private firstUrl: string | null = null
    private clickCount: number = 0
    private keypressCount: number = 0
    private mouseActivityCount: number = 0
    private messageCount: number = 0
    private snapshotSource: string | null = null
    private snapshotLibrary: string | null = null
    private segmentationEvents: SegmentationEvent[] = []
    private droppedUrlsCount: number = 0

    constructor(
        public readonly sessionId: string,
        public readonly teamId: number,
        public readonly batchId: string
    ) {}

    /**
     * Aggregates one message's precomputed session data ({@link serializeSessionData}) into the
     * session block: appends the serialized chunks and folds the counts, urls, and ranges in.
     * Buffered until end() is called.
     *
     * @returns Number of raw bytes written (before compression)
     * @throws If called after end()
     */
    public recordSessionData(data: SerializedSessionData): number {
        if (this.ended) {
            throw new Error('Cannot record message after end() has been called')
        }

        if (!this._distinctId) {
            this._distinctId = data.distinctId
        }
        if (!this.snapshotSource) {
            this.snapshotSource = data.snapshotSource
        }
        if (!this.snapshotLibrary) {
            this.snapshotLibrary = data.snapshotLibrary
        }

        // Note: We don't need to check for zero timestamps here because:
        // 1. The parse step filters out events with zero timestamps
        // 2. The parse step drops messages with no valid events
        // Therefore, eventsRange.start and eventsRange.end will always be present and non-zero
        if (!this.startDateTime || data.eventsRange.start < this.startDateTime) {
            this.startDateTime = data.eventsRange.start
        }
        if (!this.endDateTime || data.eventsRange.end > this.endDateTime) {
            this.endDateTime = data.eventsRange.end
        }

        this.uncompressedChunks.push(...data.chunks)
        this.segmentationEvents.push(...data.segmentationEvents)
        for (const url of data.urls) {
            this.addUrl(url)
        }
        this.clickCount += data.clickCount
        this.keypressCount += data.keypressCount
        this.mouseActivityCount += data.mouseActivityCount
        this.eventCount += data.eventCount
        this.size += data.rawBytes
        this.messageCount += 1
        return data.rawBytes
    }

    private addUrl(url: string): void {
        if (!url) {
            return
        }

        const truncatedUrl = url.length > MAX_URL_LENGTH ? url.slice(0, MAX_URL_LENGTH) : url
        if (url.length > MAX_URL_LENGTH) {
            logger.warn(
                '🔗',
                `Truncating URL from ${url.length} to ${MAX_URL_LENGTH} characters for session ${this.sessionId}`
            )
        }

        if (!this.firstUrl) {
            this.firstUrl = truncatedUrl
        }
        if (this.urls.size < MAX_URLS_COUNT) {
            this.urls.add(truncatedUrl)
        } else {
            this.droppedUrlsCount++
            logger.warn(
                '🔗',
                `Dropping URL (count limit reached) for session ${this.sessionId} team ${this.teamId}, dropped ${this.droppedUrlsCount} URLs`
            )
        }
    }

    /**
     * The distinct_id associated with this session recording
     */
    public get distinctId(): string {
        if (!this._distinctId) {
            throw new Error('No distinct_id set. No messages recorded yet.')
        }
        return this._distinctId
    }

    /**
     * Finalizes the session recording and returns the compressed buffer with metadata
     *
     * @returns The compressed session recording block with metadata
     * @throws If called more than once
     */
    public async end(): Promise<EndResult> {
        if (this.ended) {
            throw new Error('end() has already been called')
        }
        this.ended = true

        // Buffer.concat typings are missing the signature with Buffer[]
        const uncompressedBuffer = Buffer.concat(this.uncompressedChunks as any)
        const buffer = await snappy.compress(uncompressedBuffer)

        // Calculate active time using segmentation events
        const activeTime = activeMillisecondsFromSegmentationEvents(this.segmentationEvents)

        return {
            buffer,
            eventCount: this.eventCount,
            startDateTime: this.startDateTime ?? DateTime.fromMillis(0),
            endDateTime: this.endDateTime ?? DateTime.fromMillis(0),
            firstUrl: this.firstUrl,
            urls: Array.from(this.urls),
            clickCount: this.clickCount,
            keypressCount: this.keypressCount,
            mouseActivityCount: this.mouseActivityCount,
            activeMilliseconds: activeTime,
            size: this.size,
            messageCount: this.messageCount,
            snapshotSource: this.snapshotSource,
            snapshotLibrary: this.snapshotLibrary,
            batchId: this.batchId,
        }
    }
}
