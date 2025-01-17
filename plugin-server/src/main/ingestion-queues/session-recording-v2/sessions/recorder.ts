import { Writable } from 'stream'

import { ParsedMessageData } from '../kafka/types'

export class SessionRecorder {
    private chunks: string[] = []
    private size: number = 0

    public recordMessage(message: ParsedMessageData): number {
        let bytesWritten = 0

        Object.entries(message.eventsByWindowId).forEach(([windowId, events]) => {
            events.forEach((event) => {
                const serializedLine = JSON.stringify([windowId, event]) + '\n'
                this.chunks.push(serializedLine)
                bytesWritten += Buffer.byteLength(serializedLine)
            })
        })

        this.size += bytesWritten
        return bytesWritten
    }

    public async dump(stream: Writable): Promise<void> {
        for (const chunk of this.chunks) {
            if (!stream.write(chunk)) {
                // Handle backpressure
                await new Promise((resolve) => stream.once('drain', resolve))
            }
        }
    }
}
