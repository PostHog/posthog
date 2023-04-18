import { Consumer } from 'kafkajs'

import { OffsetManager } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/offset-manager'

describe('offset-manager', () => {
    const TOPIC = 'test-session-recordings'

    let offsetManager: OffsetManager
    const mockConsumer = {
        commitOffsets: jest.fn(() => Promise.resolve()),
    }

    beforeEach(() => {
        mockConsumer.commitOffsets.mockClear()
        offsetManager = new OffsetManager(mockConsumer as unknown as Consumer)
    })

    it('collects new offsets', () => {
        offsetManager.addOffset(TOPIC, 1, 1)
        offsetManager.addOffset(TOPIC, 2, 1)
        offsetManager.addOffset(TOPIC, 3, 4)
        offsetManager.addOffset(TOPIC, 1, 2)
        offsetManager.addOffset(TOPIC, 1, 5)
        offsetManager.addOffset(TOPIC, 3, 4)

        expect(offsetManager.offsetsByPartionTopic).toEqual(
            new Map([
                ['test-session-recordings-1', [1, 2, 5]],
                ['test-session-recordings-2', [1]],
                ['test-session-recordings-3', [4, 4]],
            ])
        )
    })

    it('removes offsets', async () => {
        offsetManager.addOffset(TOPIC, 1, 1)
        offsetManager.addOffset(TOPIC, 2, 1)
        offsetManager.addOffset(TOPIC, 3, 4)
        offsetManager.addOffset(TOPIC, 1, 2)
        offsetManager.addOffset(TOPIC, 1, 5)
        offsetManager.addOffset(TOPIC, 3, 4)

        await offsetManager.removeOffsets(TOPIC, 1, [1, 2])

        expect(offsetManager.offsetsByPartionTopic).toEqual(
            new Map([
                ['test-session-recordings-1', [5]],
                ['test-session-recordings-2', [1]],
                ['test-session-recordings-3', [4, 4]],
            ])
        )
    })

    it.each([
        [[1], 1],
        [[2, 5, 10], null],
        [[1, 2, 3, 9], 3],
    ])('commits the appropriate offset ', async (removals: number[], expectation: number | null) => {
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((offset) => {
            offsetManager.addOffset(TOPIC, 1, offset)
        })

        const result = await offsetManager.removeOffsets(TOPIC, 1, removals)

        expect(result).toEqual(expectation)
    })
})
