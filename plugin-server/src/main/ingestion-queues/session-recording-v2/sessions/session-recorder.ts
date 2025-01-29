import { Readable } from 'stream'
import { createGzip } from 'zlib'

import { ParsedMessageData } from '../kafka/types'

export interface EndResult {
    /** A readable stream containing the gzipped session block */
    stream: Readable
    /** Number of events in the session block */
    eventCount: number
}

/**
 * Records events for a single session recording
 *
 * Buffers events and provides them as a gzipped session recording block that can be
 * stored in a session batch file. The session recording block can be read as an independent unit.
 *
 * ```
 * Session Batch File
 * ├── Gzipped Session Recording Block 1 <── One SessionRecorder corresponds to one block
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       ├── [windowId, event2]
 * │       └── ...
 * ├── Gzipped Session Recording Block 2
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       └── ...
 * └── ...
 * ```
 *
 * The session block format (after decompression) is a sequence of newline-delimited JSON records.
 * Each record is an array of [windowId, event].
 */
export class SessionRecorder {
    private readonly gzip: ReturnType<typeof createGzip>
    private eventCount: number = 0
    private rawBytesWritten: number = 0

    constructor() {
        this.gzip = createGzip()
    }

    /**
     * Records a message containing events for this session
     * Events are added to the gzip buffer immediately
     *
     * @param message - Message containing events for one or more windows
     * @returns Number of raw bytes written (before compression)
     */
    public recordMessage(message: ParsedMessageData): number {
        let rawBytesWritten = 0

        Object.entries(message.eventsByWindowId).forEach(([windowId, events]) => {
            events.forEach((event) => {
                const serializedLine = JSON.stringify([windowId, event]) + '\n'
                // No need to handle backpressure here as gzip buffers until end() is called
                // There is a test that covers writing large amounts of data
                this.gzip.write(serializedLine)
                rawBytesWritten += Buffer.byteLength(serializedLine)
                this.eventCount++
            })
        })

        this.rawBytesWritten += rawBytesWritten
        return rawBytesWritten
    }

    /**
     * Finalizes the session block and returns a stream for reading it
     *
     * The returned stream contains the gzipped session block data.
     * After calling this method, no more events can be recorded.
     */
    public end(): EndResult {
        // We end the gzip stream, so that it can be read by the consumer
        // Error handling is deferred to the consumer
        this.gzip.end()
        return {
            stream: this.gzip,
            eventCount: this.eventCount,
        }
    }
}
