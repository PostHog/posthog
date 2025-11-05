import { DateTime } from 'luxon'
import snappy from 'snappy'

import { eventPassesMetadataSwitchoverTest } from '~/main/utils'
import { SessionRecordingV2MetadataSwitchoverDate } from '~/types'

import { logger } from '../../../../utils/logger'
import { ParsedMessageData } from '../kafka/types'
import { hrefFrom, isClick, isKeypress, isMouseActivity } from '../rrweb-types'
import { SegmentationEvent, activeMillisecondsFromSegmentationEvents, toSegmentationEvent } from '../segmentation'

const MAX_SNAPSHOT_FIELD_LENGTH = 1000
const MAX_URL_LENGTH = 4 * 1024 // 4KB
const MAX_URLS_COUNT = 25

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
        public readonly batchId: string,
        private readonly metadataSwitchoverDate: SessionRecordingV2MetadataSwitchoverDate
    ) {}

    /**
     * Records a message containing events for this session
     * Events are buffered until end() is called
     *
     * @param message - Message containing events for one or more windows
     * @returns Number of raw bytes written (before compression)
     * @throws If called after end()
     */
    public recordMessage(message: ParsedMessageData): number {
        if (this.ended) {
            throw new Error('Cannot record message after end() has been called')
        }

        if (!this._distinctId) {
            this._distinctId = message.distinct_id
        }

        if (!this.snapshotSource) {
            this.snapshotSource = (message.snapshot_source || 'web').slice(0, MAX_SNAPSHOT_FIELD_LENGTH)
        }
        if (!this.snapshotLibrary) {
            this.snapshotLibrary = message.snapshot_library
                ? message.snapshot_library.slice(0, MAX_SNAPSHOT_FIELD_LENGTH)
                : null
        }

        let rawBytesWritten = 0

        // Note: We don't need to check for zero timestamps here because:
        // 1. KafkaMessageParser filters out events with zero timestamps
        // 2. KafkaMessageParser drops messages with no events
        // Therefore, eventsRange.start and eventsRange.end will always be present and non-zero
        if (!this.startDateTime || message.eventsRange.start < this.startDateTime) {
            this.startDateTime = message.eventsRange.start
        }
        if (!this.endDateTime || message.eventsRange.end > this.endDateTime) {
            this.endDateTime = message.eventsRange.end
        }

        for (const [windowId, events] of Object.entries(message.eventsByWindowId)) {
            for (const event of events) {
                const serializedLine = JSON.stringify([windowId, event]) + '\n'
                const chunk = Buffer.from(serializedLine)
                this.uncompressedChunks.push(chunk)

                const eventTimestamp = event.timestamp
                const shouldComputeMetadata = eventPassesMetadataSwitchoverTest(
                    eventTimestamp,
                    this.metadataSwitchoverDate
                )

                if (shouldComputeMetadata) {
                    // Store segmentation event for later use in active time calculation
                    this.segmentationEvents.push(toSegmentationEvent(event))

                    const eventUrl = hrefFrom(event)
                    if (eventUrl) {
                        this.addUrl(eventUrl)
                    }

                    if (isClick(event)) {
                        this.clickCount += 1
                    }

                    if (isKeypress(event)) {
                        this.keypressCount += 1
                    }

                    if (isMouseActivity(event)) {
                        this.mouseActivityCount += 1
                    }

                    this.eventCount++
                    this.size += chunk.length
                }

                rawBytesWritten += chunk.length
            }
        }

        this.messageCount += 1
        return rawBytesWritten
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
