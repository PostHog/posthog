import { KafkaConsumer } from 'node-rdkafka-acosom'

import { OffsetManager } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/offset-manager'

describe('offset-manager', () => {
    const TOPIC = 'test-session-recordings'

    let offsetManager: OffsetManager
    const mockConsumer = {
        commit: jest.fn(() => Promise.resolve()),
    }

    beforeEach(() => {
        mockConsumer.commit.mockClear()
        offsetManager = new OffsetManager(mockConsumer as unknown as KafkaConsumer)
    })

    it('collects new offsets', () => {
        offsetManager.addOffset(TOPIC, 1, 1)
        offsetManager.addOffset(TOPIC, 2, 1)
        offsetManager.addOffset(TOPIC, 3, 4)
        offsetManager.addOffset(TOPIC, 1, 2)
        offsetManager.addOffset(TOPIC, 1, 5)
        offsetManager.addOffset(TOPIC, 3, 4)

        expect(offsetManager.offsetsByPartitionTopic).toEqual(
            new Map([
                ['test-session-recordings-1', [1, 2, 5]],
                ['test-session-recordings-2', [1]],
                ['test-session-recordings-3', [4, 4]],
            ])
        )
    })

    it('removes offsets', () => {
        offsetManager.addOffset(TOPIC, 1, 1)
        offsetManager.addOffset(TOPIC, 2, 1)
        offsetManager.addOffset(TOPIC, 3, 4)
        offsetManager.addOffset(TOPIC, 1, 2)
        offsetManager.addOffset(TOPIC, 1, 5)
        offsetManager.addOffset(TOPIC, 3, 4)

        offsetManager.removeOffsets(TOPIC, 1, [1, 2])

        expect(offsetManager.offsetsByPartitionTopic).toEqual(
            new Map([
                ['test-session-recordings-1', [5]],
                ['test-session-recordings-2', [1]],
                ['test-session-recordings-3', [4, 4]],
            ])
        )
    })

    it.each([
        [[1], 1],
        [[2, 5, 10], undefined],
        [[1, 2, 3, 9], 3],
    ])('commits the appropriate offset ', (removals: number[], expectation: number | null | undefined) => {
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((offset) => {
            offsetManager.addOffset(TOPIC, 1, offset)
        })

        const result = offsetManager.removeOffsets(TOPIC, 1, removals)

        expect(result).toEqual(expectation)
        if (result === undefined) {
            expect(mockConsumer.commit).toHaveBeenCalledTimes(0)
        } else {
            expect(mockConsumer.commit).toHaveBeenCalledTimes(1)
            expect(mockConsumer.commit).toHaveBeenCalledWith({
                offset: result,
                partition: 1,
                topic: 'test-session-recordings',
            })
        }
    })

    it('does not commits revoked partition offsets ', () => {
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((offset) => {
            offsetManager.addOffset(TOPIC, 1, offset)
        })

        offsetManager.addOffset(TOPIC, 1, 1)
        offsetManager.addOffset(TOPIC, 2, 2)
        offsetManager.addOffset(TOPIC, 3, 3)

        offsetManager.revokePartitions(TOPIC, [1])

        const resultOne = offsetManager.removeOffsets(TOPIC, 1, [1])
        expect(resultOne).toEqual(undefined)
        expect(mockConsumer.commit).toHaveBeenCalledTimes(0)

        mockConsumer.commit.mockClear()

        const resultTwo = offsetManager.removeOffsets(TOPIC, 2, [2])
        expect(resultTwo).toEqual(2)
        expect(mockConsumer.commit).toHaveBeenCalledTimes(1)

        mockConsumer.commit.mockClear()

        const resultThree = offsetManager.removeOffsets(TOPIC, 3, [3])
        expect(resultThree).toEqual(3)
        expect(mockConsumer.commit).toHaveBeenCalledTimes(1)
    })
})
