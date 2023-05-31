import { DateTime } from 'luxon'

import { PendingChunks } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/pending-chunks'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/types'

function shuffleArray(array: Array<any>) {
    for (let i = array.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1))
        ;[array[i], array[j]] = [array[j], array[i]]
    }
    // alters the original array, but returns it to make life easier
    return array
}

describe('pending chunks', () => {
    const now = DateTime.now()

    it.each([
        ['can be idle on the boundary', [5 * 60 * 1000], 5 * 60 * 1000, true],
        ['can be idle with several messages', [4 * 60 * 1000, 5 * 60 * 1000], 5 * 60 * 1000, true],
        ['can be not idle with several messages', [4 * 60 * 1000, 3 * 60 * 1000], 5 * 60 * 1000, false],
        ['can be idle just after the boundary', [5 * 60 * 1000 + 1], 5 * 60 * 1000, true],
        ['is not idle just before the boundary', [5 * 60 * 1000 - 1], 5 * 60 * 1000, false],
    ])('isIdle - %s', (_description: string, chunkSkews: number[], idleThreshold: number, expectedIdle: boolean) => {
        const chunks = chunkSkews.map((chunkSkew) => {
            const chunkTime = now.minus({ milliseconds: chunkSkew }).toMillis()
            return { metadata: { timestamp: chunkTime } } as IncomingRecordingMessage
        })

        const pc = new PendingChunks(chunks[0])
        chunks.slice(1).forEach((chunk) => pc.add(chunk))

        const actual = pc.isIdle(now.toMillis(), idleThreshold)

        expect(actual).toBe(expectedIdle)
    })

    it('can complete an array regardless of order it receives chunks', () => {
        const pc = new PendingChunks({
            chunk_id: 'testme',
            chunk_index: 0,
            chunk_count: 28,
        } as IncomingRecordingMessage)

        const numbers = shuffleArray(Array.from(Array(27).keys()))
        numbers.forEach((i) => {
            pc.add({
                chunk_id: 'testme',
                chunk_index: i + 1,
                chunk_count: 28,
            } as IncomingRecordingMessage)
        })

        expect(pc.count).toBe(28)
        expect(pc.expectedSize).toBe(28)
        expect(pc.isComplete).toBe(true)
        expect(pc.completedChunks.map((c) => c.chunk_index)).toStrictEqual([
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27,
        ])
    })
})
