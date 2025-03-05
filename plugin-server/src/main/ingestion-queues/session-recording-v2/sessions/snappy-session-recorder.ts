import { DateTime } from 'luxon'
import snappy from 'snappy'

import { ParsedMessageData } from '../kafka/types'

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

        // Store the distinctId from the first message if not already set
        if (!this._distinctId) {
            this._distinctId = message.distinct_id
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

        Object.entries(message.eventsByWindowId).forEach(([windowId, events]) => {
            events.forEach((event) => {
                const serializedLine = JSON.stringify([windowId, event]) + '\n'
                const chunk = Buffer.from(serializedLine)
                this.uncompressedChunks.push(chunk)
                rawBytesWritten += chunk.length
                this.eventCount++
            })
        })

        this.rawBytesWritten += rawBytesWritten
        return rawBytesWritten
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

        return {
            buffer,
            eventCount: this.eventCount,
            startDateTime: this.startDateTime ?? DateTime.fromMillis(0),
            endDateTime: this.endDateTime ?? DateTime.fromMillis(0),
            firstUrl: null,
            urls: [],
            clickCount: 0,
            keypressCount: 0,
            mouseActivityCount: 0,
            activeMilliseconds: 0,
            consoleLogCount: 0,
            consoleWarnCount: 0,
            consoleErrorCount: 0,
            size: buffer.length,
            messageCount: 0,
            snapshotSource: null,
            snapshotLibrary: null,
        }
    }
}
