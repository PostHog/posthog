import { Readable } from 'stream'
import { createGzip } from 'zlib'

import { ParsedMessageData } from '../kafka/types'

export interface EndResult {
    stream: Readable
    eventCount: number
}

export class SessionRecorder {
    private readonly gzip: ReturnType<typeof createGzip>
    private eventCount: number = 0
    private rawBytesWritten: number = 0

    constructor() {
        this.gzip = createGzip()
    }

    public recordMessage(message: ParsedMessageData): number {
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

    public end(): EndResult {
        this.gzip.end()
        return {
            stream: this.gzip,
            eventCount: this.eventCount,
        }
    }
}
