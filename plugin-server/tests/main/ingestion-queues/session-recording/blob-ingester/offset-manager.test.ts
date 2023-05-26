import { KafkaConsumer } from 'node-rdkafka-acosom'

import { OffsetManager } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/offset-manager'

describe('offset-manager', () => {
    const TOPIC = 'test-session-recordings'

    let offsetManager: OffsetManager
    const mockConsumer = {
        commitSync: jest.fn(() => Promise.resolve()),
    }

    beforeEach(() => {
        mockConsumer.commitSync.mockClear()
        offsetManager = new OffsetManager(mockConsumer as unknown as KafkaConsumer)
    })

    it('collects new offsets', () => {
        offsetManager.addOffset(TOPIC, 1, 'session_id_1', 1)
        offsetManager.addOffset(TOPIC, 2, 'session_id', 1)
        offsetManager.addOffset(TOPIC, 1, 'session_id_2', 2)
        offsetManager.addOffset(TOPIC, 3, 'session_id', 4)
        offsetManager.addOffset(TOPIC, 1, 'session_id_1', 5)
        offsetManager.addOffset(TOPIC, 3, 'session_id', 3)
        // even if the offsets arrive out of order
        offsetManager.addOffset(TOPIC, 3, 'session_id', 7)
        offsetManager.addOffset(TOPIC, 3, 'session_id', 6)
        offsetManager.addOffset(TOPIC, 3, 'session_id', 8)
        offsetManager.addOffset(TOPIC, 3, 'session_id', 0)

        expect(offsetManager.offsetsByPartitionTopic).toEqual(
            new Map([
                [
                    'test-session-recordings-1',
                    [
                        { session_id: 'session_id_1', offset: 1 },
                        { session_id: 'session_id_2', offset: 2 },
                        { session_id: 'session_id_1', offset: 5 },
                    ],
                ],
                ['test-session-recordings-2', [{ session_id: 'session_id', offset: 1 }]],
                [
                    'test-session-recordings-3',
                    [
                        // if received out of order, we don't sort them
                        // we only sort them on removal, to avoid sorting too many times
                        { session_id: 'session_id', offset: 4 },
                        { session_id: 'session_id', offset: 3 },
                        { session_id: 'session_id', offset: 7 },
                        { session_id: 'session_id', offset: 6 },
                        { session_id: 'session_id', offset: 8 },
                        { session_id: 'session_id', offset: 0 },
                    ],
                ],
            ])
        )
    })

    it('removes offsets', () => {
        offsetManager.addOffset(TOPIC, 1, 'session_id', 1)
        offsetManager.addOffset(TOPIC, 2, 'session_id', 1)
        offsetManager.addOffset(TOPIC, 3, 'session_id', 4)
        offsetManager.addOffset(TOPIC, 1, 'session_id', 2)
        offsetManager.addOffset(TOPIC, 1, 'session_id', 5)
        offsetManager.addOffset(TOPIC, 3, 'session_id', 4)

        offsetManager.removeOffsets(TOPIC, 1, [1, 2])

        expect(offsetManager.offsetsByPartitionTopic).toEqual(
            new Map([
                ['test-session-recordings-1', [{ session_id: 'session_id', offset: 5 }]],
                ['test-session-recordings-2', [{ session_id: 'session_id', offset: 1 }]],
                [
                    'test-session-recordings-3',
                    [
                        { session_id: 'session_id', offset: 4 },
                        { session_id: 'session_id', offset: 4 },
                    ],
                ],
            ])
        )
    })

    it.each([
        [[], undefined],
        [[1], 1],
        [[2, 5, 10], undefined],
        [[1, 2, 3, 9], 3],
    ])('commits the appropriate offset ', (removals: number[], expectedCommittedOffset: number | null | undefined) => {
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((offset) => {
            offsetManager.addOffset(TOPIC, 1, 'session_id', offset)
        })

        const result = offsetManager.removeOffsets(TOPIC, 1, removals)

        expect(result).toEqual(expectedCommittedOffset)
        if (result === undefined) {
            expect(mockConsumer.commitSync).toHaveBeenCalledTimes(0)
        } else {
            expect(mockConsumer.commitSync).toHaveBeenCalledTimes(1)
            expect(mockConsumer.commitSync).toHaveBeenCalledWith({
                offset: result + 1, // why oh why
                partition: 1,
                topic: 'test-session-recordings',
            })
        }
    })

    it('does not commits revoked partition offsets ', () => {
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((offset) => {
            offsetManager.addOffset(TOPIC, 1, 'session_id', offset)
        })
        expect(offsetManager.offsetsByPartitionTopic.size).toEqual(1)
        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-1`)).toEqual([
            { offset: 1, session_id: 'session_id' },
            { offset: 2, session_id: 'session_id' },
            { offset: 3, session_id: 'session_id' },
            { offset: 4, session_id: 'session_id' },
            { offset: 5, session_id: 'session_id' },
            { offset: 6, session_id: 'session_id' },
            { offset: 7, session_id: 'session_id' },
            { offset: 8, session_id: 'session_id' },
            { offset: 9, session_id: 'session_id' },
            { offset: 10, session_id: 'session_id' },
        ])

        offsetManager.addOffset(TOPIC, 1, 'session_id', 1)

        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-1`)).toEqual([
            { offset: 1, session_id: 'session_id' },
            { offset: 2, session_id: 'session_id' },
            { offset: 3, session_id: 'session_id' },
            { offset: 4, session_id: 'session_id' },
            { offset: 5, session_id: 'session_id' },
            { offset: 6, session_id: 'session_id' },
            { offset: 7, session_id: 'session_id' },
            { offset: 8, session_id: 'session_id' },
            { offset: 9, session_id: 'session_id' },
            { offset: 10, session_id: 'session_id' },
            { offset: 1, session_id: 'session_id' },
        ])

        offsetManager.addOffset(TOPIC, 2, 'session_id', 2)

        expect(offsetManager.offsetsByPartitionTopic.size).toEqual(2)
        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-1`)).toEqual([
            { offset: 1, session_id: 'session_id' },
            { offset: 2, session_id: 'session_id' },
            { offset: 3, session_id: 'session_id' },
            { offset: 4, session_id: 'session_id' },
            { offset: 5, session_id: 'session_id' },
            { offset: 6, session_id: 'session_id' },
            { offset: 7, session_id: 'session_id' },
            { offset: 8, session_id: 'session_id' },
            { offset: 9, session_id: 'session_id' },
            { offset: 10, session_id: 'session_id' },
            { offset: 1, session_id: 'session_id' },
        ])
        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-2`)).toEqual([
            { offset: 2, session_id: 'session_id' },
        ])

        offsetManager.addOffset(TOPIC, 3, 'session_id', 3)

        expect(offsetManager.offsetsByPartitionTopic.size).toEqual(3)
        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-1`)).toEqual([
            { offset: 1, session_id: 'session_id' },
            { offset: 2, session_id: 'session_id' },
            { offset: 3, session_id: 'session_id' },
            { offset: 4, session_id: 'session_id' },
            { offset: 5, session_id: 'session_id' },
            { offset: 6, session_id: 'session_id' },
            { offset: 7, session_id: 'session_id' },
            { offset: 8, session_id: 'session_id' },
            { offset: 9, session_id: 'session_id' },
            { offset: 10, session_id: 'session_id' },
            { offset: 1, session_id: 'session_id' },
        ])
        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-2`)).toEqual([
            { offset: 2, session_id: 'session_id' },
        ])
        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-3`)).toEqual([
            { offset: 3, session_id: 'session_id' },
        ])

        expect(offsetManager.offsetsByPartitionTopic.has(`${TOPIC}-1`)).toEqual(true)
        offsetManager.revokePartitions(TOPIC, [1])
        expect(offsetManager.offsetsByPartitionTopic.has(`${TOPIC}-1`)).toEqual(false)

        expect(() => offsetManager.removeOffsets(TOPIC, 1, [1])).not.toThrow(
            'No in-flight offsets found for partition 1'
        )
        expect(mockConsumer.commitSync).toHaveBeenCalledTimes(0)

        mockConsumer.commitSync.mockClear()

        const resultTwo = offsetManager.removeOffsets(TOPIC, 2, [2])
        expect(resultTwo).toEqual(2)
        expect(mockConsumer.commitSync).toHaveBeenCalledWith({
            offset: 3,
            partition: 2,
            topic: 'test-session-recordings',
        })

        mockConsumer.commitSync.mockClear()

        const resultThree = offsetManager.removeOffsets(TOPIC, 3, [3])
        expect(resultThree).toEqual(3)
        expect(mockConsumer.commitSync).toHaveBeenCalledWith({
            offset: 4,
            partition: 3,
            topic: 'test-session-recordings',
        })
    })

    it('if a partition was not revoked, then it must have offsets when they are requested for removal ', () => {
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((offset) => {
            offsetManager.addOffset(TOPIC, 1, 'session_id', offset)
        })

        expect(offsetManager.offsetsByPartitionTopic.get(`${TOPIC}-1`)?.length).toEqual(10)
        expect(offsetManager.offsetsByPartitionTopic.has(`${TOPIC}-1`)).toEqual(true)

        // revoke partition 1 - as if a rebalance has happened
        offsetManager.revokePartitions(TOPIC, [1])
        expect(offsetManager.offsetsByPartitionTopic.has(`${TOPIC}-1`)).toEqual(false)

        // reassign partition 1 - as if a rebalance has happened
        offsetManager.assignPartition(TOPIC, [1])

        expect(() => offsetManager.removeOffsets(TOPIC, 1, [1])).toThrow('No in-flight offsets found for partition 1')
        expect(mockConsumer.commitSync).toHaveBeenCalledTimes(0)
    })

    it('keeps track of revoked partitions', () => {
        // we see session managers try to remove partitions for untracked partitions but don't know why
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((partition) => {
            offsetManager.addOffset(TOPIC, partition, 'session_id', partition * 2)
        })

        offsetManager.revokePartitions(TOPIC, [1, 2, 3, 4])
        expect(Array.from(offsetManager.offsetsByPartitionTopic.keys())).toEqual([
            `${TOPIC}-5`,
            `${TOPIC}-6`,
            `${TOPIC}-7`,
            `${TOPIC}-8`,
            `${TOPIC}-9`,
            `${TOPIC}-10`,
        ])

        expect(offsetManager.revokedPartitions).toEqual({
            [TOPIC]: new Set([1, 2, 3, 4]),
        })

        offsetManager.assignPartition(TOPIC, [1, 4])
        expect(offsetManager.revokedPartitions).toEqual({
            [TOPIC]: new Set([2, 3]),
        })
    })
})
