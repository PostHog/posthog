import { IncomingRecordingMessage } from './types'

export class PendingChunks {
    readonly chunks: IncomingRecordingMessage[]
    readonly expectedSize: number

    constructor(messages: IncomingRecordingMessage[]) {
        if (messages.length === 0) {
            throw new Error('Cannot create PendingChunks with no messages')
        }
        this.chunks = messages
        this.expectedSize = messages[0].chunk_count
        this.onAddMessage()
    }

    get count() {
        return this.chunks.length
    }

    get isComplete() {
        const fullSet = this.chunks.slice(0, this.expectedSize)
        const expectedChunkIndexes = Array.from(Array(this.expectedSize).keys())
        const chunkIndexes = fullSet.map((x) => x.chunk_index)
        return expectedChunkIndexes.every((x, i) => chunkIndexes[i] === x)
    }

    get completedChunks() {
        if (!this.isComplete) {
            throw new Error('Cannot get completed chunks from incomplete set')
        }
        return this.chunks.slice(0, this.expectedSize)
    }

    isIdle(referenceNow: number, idleThreshold: number) {
        const lastChunk = this.chunks[this.chunks.length - 1]
        return lastChunk.metadata.timestamp < referenceNow - idleThreshold
    }

    add(message: IncomingRecordingMessage) {
        this.chunks.push(message)
        this.onAddMessage()
    }

    private onAddMessage() {
        this.chunks.sort((a, b) => {
            if (a.chunk_index === b.chunk_index) {
                return a.metadata.timestamp - b.metadata.timestamp
            }
            return a.chunk_index - b.chunk_index
        })
    }
}
