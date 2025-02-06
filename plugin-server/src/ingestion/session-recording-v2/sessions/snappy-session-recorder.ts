import snappy from 'snappy'

import { ParsedMessageData } from '../kafka/types'

export interface EndResult {
    /** The complete compressed session block */
    buffer: Buffer
    /** Number of events in the session block */
    eventCount: number
    /** Timestamp of the first event in the session block */
    startTimestamp: number
    /** Timestamp of the last event in the session block */
    endTimestamp: number
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
    private startTimestamp: number | null = null
    private endTimestamp: number | null = null

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

        let rawBytesWritten = 0

        // Note: We don't need to check for zero timestamps here because:
        // 1. KafkaMessageParser filters out events with zero timestamps
        // 2. KafkaMessageParser drops messages with no events
        // Therefore, eventsRange.start and eventsRange.end will always be present and non-zero
        this.startTimestamp =
            this.startTimestamp === null
                ? message.eventsRange.start
                : Math.min(this.startTimestamp, message.eventsRange.start)
        this.endTimestamp =
            this.endTimestamp === null ? message.eventsRange.end : Math.max(this.endTimestamp, message.eventsRange.end)

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
     * Finalizes and returns the compressed session block
     *
     * @returns The complete compressed session block and event count
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
            startTimestamp: this.startTimestamp ?? 0,
            endTimestamp: this.endTimestamp ?? 0,
        }
    }
}
