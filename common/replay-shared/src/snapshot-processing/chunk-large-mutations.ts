import { EventType, IncrementalSource } from '@posthog/rrweb-types'

import { RecordingSnapshot } from '../types'

export const MUTATION_CHUNK_SIZE = 5000

export function chunkMutationSnapshot(snapshot: RecordingSnapshot): RecordingSnapshot[] {
    if (
        snapshot.type !== EventType.IncrementalSnapshot ||
        !('data' in snapshot) ||
        !snapshot.data ||
        typeof snapshot.data !== 'object' ||
        !('source' in snapshot.data) ||
        snapshot.data.source !== IncrementalSource.Mutation ||
        !('adds' in snapshot.data) ||
        !Array.isArray(snapshot.data.adds) ||
        snapshot.data.adds.length <= MUTATION_CHUNK_SIZE
    ) {
        return [snapshot]
    }

    const chunks: RecordingSnapshot[] = []
    const { adds, removes, texts, attributes } = snapshot.data
    const totalAdds = adds.length
    const chunksCount = Math.ceil(totalAdds / MUTATION_CHUNK_SIZE)

    for (let i = 0; i < chunksCount; i++) {
        const startIdx = i * MUTATION_CHUNK_SIZE
        const endIdx = Math.min((i + 1) * MUTATION_CHUNK_SIZE, totalAdds)
        const isFirstChunk = i === 0
        const isLastChunk = i === chunksCount - 1

        const chunkSnapshot: RecordingSnapshot = {
            ...snapshot,
            timestamp: snapshot.timestamp,
            data: {
                ...snapshot.data,
                adds: adds.slice(startIdx, endIdx),
                removes: isFirstChunk ? removes : [],
                texts: isLastChunk ? texts : [],
                attributes: isLastChunk ? attributes : [],
            },
        }

        if ('delay' in snapshot) {
            chunkSnapshot.delay = snapshot.delay || 0
        }

        chunks.push(chunkSnapshot)
    }

    return chunks
}
