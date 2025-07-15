import { KafkaOffsetManager } from './offset-manager'

describe('KafkaOffsetManager', () => {
    let offsetManager: KafkaOffsetManager
    let mockCommitOffsets: jest.Mock<Promise<void>>
    const TEST_TOPIC = 'test_topic'

    beforeEach(() => {
        mockCommitOffsets = jest.fn().mockResolvedValue(undefined)
        offsetManager = new KafkaOffsetManager(mockCommitOffsets, TEST_TOPIC)
    })

    it('should track offsets when recording messages', async () => {
        offsetManager.trackOffset({ partition: 1, offset: 100 })

        await offsetManager.commit()

        expect(mockCommitOffsets).toHaveBeenCalledWith([{ topic: TEST_TOPIC, partition: 1, offset: 101 }])
    })

    it('should commit offsets for multiple partitions', async () => {
        const messages = [
            { partition: 1, offset: 100 },
            { partition: 1, offset: 101 },
            { partition: 2, offset: 200 },
        ]

        for (const metadata of messages) {
            offsetManager.trackOffset(metadata)
        }

        await offsetManager.commit()

        expect(mockCommitOffsets).toHaveBeenCalledWith([
            { topic: TEST_TOPIC, partition: 1, offset: 102 }, // Last offset + 1
            { topic: TEST_TOPIC, partition: 2, offset: 201 }, // Last offset + 1
        ])
    })

    it('should clear offsets after commit', async () => {
        offsetManager.trackOffset({ partition: 1, offset: 100 })
        await offsetManager.commit()

        // Second commit should not commit anything
        await offsetManager.commit()

        expect(mockCommitOffsets).toHaveBeenCalledTimes(1)
    })

    it('should handle commit failures', async () => {
        const error = new Error('Commit failed')
        mockCommitOffsets.mockRejectedValueOnce(error)

        offsetManager.trackOffset({ partition: 1, offset: 100 })

        await expect(offsetManager.commit()).rejects.toThrow(error)
    })

    describe('partition handling', () => {
        it('should not commit offsets for discarded partitions', async () => {
            // Record messages for two partitions
            offsetManager.trackOffset({ partition: 1, offset: 100 })
            offsetManager.trackOffset({ partition: 2, offset: 200 })

            // Discard partition 1
            offsetManager.discardPartition(1)

            await offsetManager.commit()

            // Should only commit offset for partition 2
            expect(mockCommitOffsets).toHaveBeenCalledWith([
                {
                    topic: 'test_topic',
                    partition: 2,
                    offset: 201,
                },
            ])
        })

        it('should handle discarding already committed partitions', async () => {
            // Record and commit a message
            offsetManager.trackOffset({ partition: 1, offset: 100 })
            await offsetManager.commit()

            // Discard the partition after commit
            offsetManager.discardPartition(1)

            // Record new message for same partition
            offsetManager.trackOffset({ partition: 1, offset: 101 })
            await offsetManager.commit()

            expect(mockCommitOffsets).toHaveBeenCalledTimes(2)
            expect(mockCommitOffsets).toHaveBeenLastCalledWith([
                {
                    topic: 'test_topic',
                    partition: 1,
                    offset: 102,
                },
            ])
        })

        it('should handle discarding non-existent partitions', () => {
            offsetManager.discardPartition(999)
            // No error should be thrown
        })

        it('should maintain highest offset when recording multiple messages', async () => {
            // Record messages in non-sequential order
            offsetManager.trackOffset({ partition: 1, offset: 100 })
            offsetManager.trackOffset({ partition: 1, offset: 99 })
            offsetManager.trackOffset({ partition: 1, offset: 101 })

            await offsetManager.commit()

            expect(mockCommitOffsets).toHaveBeenCalledWith([
                {
                    topic: 'test_topic',
                    partition: 1,
                    offset: 102,
                },
            ])
        })
    })
})
