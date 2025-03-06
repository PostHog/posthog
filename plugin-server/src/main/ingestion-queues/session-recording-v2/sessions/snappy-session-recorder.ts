import { DateTime } from 'luxon'
import snappy from 'snappy'

import { RRWebEvent } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'
import { ConsoleLogLevel, getConsoleLogLevel, isClick, isKeypress, isMouseActivity } from '../rrweb-types'
import { activeMillisecondsFromSegmentationEvents, SegmentationEvent, toSegmentationEvent } from '../segmentation'

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
    firstUrl?: string | null
    /** All URLs visited in the session */
    urls?: string[]
    /** Number of clicks in the session */
    clickCount?: number
    /** Number of keypresses in the session */
    keypressCount?: number
    /** Number of mouse activity events in the session */
    mouseActivityCount?: number
    /** Active time in milliseconds */
    activeMilliseconds?: number
    /** Number of console log messages */
    consoleLogCount?: number
    /** Number of console warning messages */
    consoleWarnCount?: number
    /** Number of console error messages */
    consoleErrorCount?: number
    /** Size of the session data in bytes */
    size?: number
    /** Number of messages in the session */
    messageCount?: number
    /** Source of the snapshot (Web/Mobile) */
    snapshotSource?: string | null
    /** Library used for the snapshot */
    snapshotLibrary?: string | null
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
    private rawBytesWritten: number = 0
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
    private consoleLogCount: number = 0
    private consoleWarnCount: number = 0
    private consoleErrorCount: number = 0
    private segmentationEvents: SegmentationEvent[] = []

    constructor(public readonly sessionId: string, public readonly teamId: number) {}

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
            this.snapshotSource = message.snapshot_source || 'web'
        }
        if (!this.snapshotLibrary) {
            this.snapshotLibrary = message.snapshot_library || null
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

        for (const windowId in message.eventsByWindowId) {
            const events = message.eventsByWindowId[windowId]
            for (const event of events) {
                // Store segmentation event for later use in active time calculation
                this.segmentationEvents.push(toSegmentationEvent(event))

                const eventUrl = this.hrefFrom(event)
                if (eventUrl) {
                    this.urls.add(eventUrl)
                    if (this.firstUrl === null) {
                        this.firstUrl = eventUrl
                    }
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

                const logLevel = getConsoleLogLevel(event)
                if (logLevel === ConsoleLogLevel.Log) {
                    this.consoleLogCount++
                } else if (logLevel === ConsoleLogLevel.Warn) {
                    this.consoleWarnCount++
                } else if (logLevel === ConsoleLogLevel.Error) {
                    this.consoleErrorCount++
                }

                const serializedLine = JSON.stringify([windowId, event]) + '\n'
                const chunk = Buffer.from(serializedLine)
                this.uncompressedChunks.push(chunk)
                rawBytesWritten += chunk.length
                this.eventCount++
            }
        }

        this.rawBytesWritten += rawBytesWritten
        this.messageCount += 1
        return rawBytesWritten
    }

    /**
     * Extract URL from an event using the same logic as in process-event.ts
     */
    private hrefFrom(event: RRWebEvent): string | undefined {
        const metaHref = event.data?.href?.trim()
        const customHref = event.data?.payload?.href?.trim()
        return metaHref || customHref || undefined
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
            consoleLogCount: this.consoleLogCount,
            consoleWarnCount: this.consoleWarnCount,
            consoleErrorCount: this.consoleErrorCount,
            size: uncompressedBuffer.length,
            messageCount: this.messageCount,
            snapshotSource: this.snapshotSource,
            snapshotLibrary: this.snapshotLibrary,
        }
    }
}
