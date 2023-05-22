import { IncomingRecordingMessage } from './types'

export class PendingChunks {
    readonly chunks: IncomingRecordingMessage[]
    readonly expectedSize: number

    constructor(message: IncomingRecordingMessage) {
        this.chunks = [message]
        this.expectedSize = message.chunk_count
    }

    get count() {
        return this.chunks.length
    }

    get isComplete() {
        const fullSet = this.chunks.slice(0, this.expectedSize)
        const expectedChunkIndexes = Array.from(Array(this.expectedSize).keys())
        return expectedChunkIndexes.every((x, i) => fullSet[i].chunk_index === x)
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
        this.chunks.sort((a, b) => {
            if (a.chunk_index === b.chunk_index) {
                return a.metadata.timestamp - b.metadata.timestamp
            }
            return a.chunk_index - b.chunk_index
        })
    }
}
