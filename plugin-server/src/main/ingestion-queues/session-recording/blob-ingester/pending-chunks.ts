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
        const fullSet = this.deduplicatedChunks()

        const expectedChunkIndexes = Array.from(Array(this.expectedSize).keys())
        return expectedChunkIndexes.every((x, i) => i < fullSet.length && fullSet[i].chunk_index === x)
    }

    private deduplicatedChunks() {
        return Object.values(
            // keep only one of each chunk_index, assumes any duplicates are ignorable duplicates
            this.chunks.reduce((acc, curr) => {
                if (!acc[curr.chunk_index]) {
                    acc[curr.chunk_index] = curr
                }
                return acc
            }, {} as Record<number, IncomingRecordingMessage>)
        ).slice(0, this.expectedSize)
    }

    get completedChunks() {
        if (!this.isComplete) {
            throw new Error('Cannot get completed chunks from incomplete set')
        }
        return this.deduplicatedChunks()
    }

    get allChunkOffsets(): number[] {
        return this.chunks.map((x) => x.metadata.offset)
    }

    isIdle(referenceNow: number, idleThreshold: number) {
        const lastChunk = this.chunks.sort((a, b) => a.metadata.timestamp - b.metadata.timestamp)[0]
        const chunkAge = referenceNow - lastChunk.metadata.timestamp
        return chunkAge >= idleThreshold
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

    get logContext(): Record<string, any> {
        const sortedChunks = this.chunks.sort((a, b) => a.metadata.timestamp - b.metadata.timestamp)

        return {
            chunk_count: this.expectedSize,
            chunk_indexes: this.chunks.map((x) => x.chunk_index),
            chunk_offsets_counts: this.chunks.length,
            first_chunk_timestamp: sortedChunks[0].metadata.timestamp,
            last_chunk_timestamp: sortedChunks[sortedChunks.length - 1].metadata.timestamp,
        }
    }
}
