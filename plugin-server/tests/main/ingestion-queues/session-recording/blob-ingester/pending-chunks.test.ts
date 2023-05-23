import { DateTime } from 'luxon'

import { PendingChunks } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/pending-chunks'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/types'
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
})
