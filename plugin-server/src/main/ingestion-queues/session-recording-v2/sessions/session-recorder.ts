import { createGzip } from 'zlib'

import { ParsedMessageData } from '../kafka/types'

export interface EndResult {
    /** The complete compressed session block */
    buffer: Buffer
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
    private readonly chunks: Buffer[] = []
    private eventCount: number = 0
    private rawBytesWritten: number = 0
    private ended = false
    // Store any gzip error that occurs - these should be rare/never happen in practice
    // We keep the error until end() to keep the recordMessage interface simple
    private gzipError: Error | null = null

    constructor() {
        this.gzip = createGzip()
        this.gzip.on('data', (chunk: Buffer) => {
            this.chunks.push(chunk)
        })
        this.gzip.on('error', (error) => {
            this.gzipError = error
        })
    }

    /**
     * Records a message containing events for this session
     * Events are added to the gzip buffer immediately
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

        Object.entries(message.eventsByWindowId).forEach(([windowId, events]) => {
            events.forEach((event) => {
                const serializedLine = JSON.stringify([windowId, event]) + '\n'
                this.gzip.write(serializedLine)
                rawBytesWritten += Buffer.byteLength(serializedLine)
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

        return new Promise((resolve, reject) => {
            if (this.gzipError) {
                reject(this.gzipError)
                return
            }

            this.gzip.on('end', () => {
                if (this.gzipError) {
                    reject(this.gzipError)
                    return
                }
                resolve({
                    // Buffer.concat typings are missing the signature with Buffer[]
                    buffer: Buffer.concat(this.chunks as any[]),
                    eventCount: this.eventCount,
                })
            })

            this.gzip.end()
        })
    }
}
