import { KafkaOffsetManager } from '../../../../../src/main/ingestion-queues/session-recording-v2/kafka/offset-manager'
import { SessionBatchRecorder } from '../../../../../src/main/ingestion-queues/session-recording-v2/sessions/session-batch-recorder'
import { MessageWithTeam } from '../../../../../src/main/ingestion-queues/session-recording-v2/teams/types'

describe('KafkaOffsetManager', () => {
    let offsetManager: KafkaOffsetManager
    let mockCommitOffsets: jest.Mock<Promise<void>>
    let mockRecorder: jest.Mocked<SessionBatchRecorder>
    const TEST_TOPIC = 'test_topic'

    beforeEach(() => {
        mockCommitOffsets = jest.fn().mockResolvedValue(undefined)
        mockRecorder = {
            record: jest.fn().mockReturnValue(100),
            flush: jest.fn().mockResolvedValue(undefined),
            size: 0,
            discardPartition: jest.fn(),
        } as unknown as jest.Mocked<SessionBatchRecorder>

        offsetManager = new KafkaOffsetManager(mockCommitOffsets, TEST_TOPIC)
    })

    const createMessage = (metadata: { partition: number; offset: number }): MessageWithTeam => ({
        team: {
            teamId: 1,
            consoleLogIngestionEnabled: false,
        },
        message: {
            distinct_id: 'distinct_id',
            session_id: 'session1',
            eventsByWindowId: { window1: [] },
            eventsRange: { start: 0, end: 0 },
            metadata: {
                partition: metadata.partition,
                offset: metadata.offset,
                topic: 'test_topic',
                timestamp: 0,
                rawSize: 0,
            },
        },
    })

    it('should track offsets when recording messages', async () => {
        const wrapper = offsetManager.wrapBatch(mockRecorder)
        const message: MessageWithTeam = {
            team: { teamId: 1, consoleLogIngestionEnabled: false },
            message: {
                metadata: { partition: 1, offset: 100 },
            },
        } as MessageWithTeam

        wrapper.record(message)

        await wrapper.flush()
        await offsetManager.commit()

        expect(mockCommitOffsets).toHaveBeenCalledWith([{ topic: TEST_TOPIC, partition: 1, offset: 101 }])
    })

    it('should commit offsets for multiple partitions', async () => {
        const wrapper = offsetManager.wrapBatch(mockRecorder)
        const messages = [
            { partition: 1, offset: 100 },
            { partition: 1, offset: 101 },
            { partition: 2, offset: 200 },
        ]

        for (const metadata of messages) {
            wrapper.record({
                team: { teamId: 1, consoleLogIngestionEnabled: false },
                message: { metadata },
            } as MessageWithTeam)
        }

        await wrapper.flush()
        await offsetManager.commit()

        expect(mockCommitOffsets).toHaveBeenCalledWith([
            { topic: TEST_TOPIC, partition: 1, offset: 102 }, // Last offset + 1
            { topic: TEST_TOPIC, partition: 2, offset: 201 }, // Last offset + 1
        ])
    })

    it('should clear offsets after commit', async () => {
        const wrapper = offsetManager.wrapBatch(mockRecorder)
        const message: MessageWithTeam = {
            team: { teamId: 1, consoleLogIngestionEnabled: false },
            message: {
                metadata: { partition: 1, offset: 100 },
            },
        } as MessageWithTeam

        wrapper.record(message)
        await wrapper.flush()
        await offsetManager.commit()

        // Second commit should not commit anything
        await offsetManager.commit()

        expect(mockCommitOffsets).toHaveBeenCalledTimes(1)
    })

    it('should handle commit failures', async () => {
        const error = new Error('Commit failed')
        mockCommitOffsets.mockRejectedValueOnce(error)

        const wrapper = offsetManager.wrapBatch(mockRecorder)
        wrapper.record({
            team: { teamId: 1, consoleLogIngestionEnabled: false },
            message: {
                metadata: { partition: 1, offset: 100 },
            },
        } as MessageWithTeam)

        await wrapper.flush()
        await expect(offsetManager.commit()).rejects.toThrow(error)
    })

    describe('partition handling', () => {
        it('should delegate discardPartition to inner recorder', () => {
            const wrappedBatch = offsetManager.wrapBatch(mockRecorder)
            wrappedBatch.discardPartition(1)

            expect(mockRecorder.discardPartition).toHaveBeenCalledWith(1)
        })

        it('should not commit offsets for discarded partitions', async () => {
            const wrappedBatch = offsetManager.wrapBatch(mockRecorder)

            // Record messages for two partitions
            wrappedBatch.record(createMessage({ partition: 1, offset: 100 }))
            wrappedBatch.record(createMessage({ partition: 2, offset: 200 }))

            // Discard partition 1
            wrappedBatch.discardPartition(1)

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
            const wrappedBatch = offsetManager.wrapBatch(mockRecorder)

            // Record and commit a message
            wrappedBatch.record(createMessage({ partition: 1, offset: 100 }))
            await offsetManager.commit()

            // Discard the partition after commit
            wrappedBatch.discardPartition(1)

            // Record new message for same partition
            wrappedBatch.record(createMessage({ partition: 1, offset: 101 }))
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
            const wrappedBatch = offsetManager.wrapBatch(mockRecorder)
            wrappedBatch.discardPartition(999)
            expect(mockRecorder.discardPartition).toHaveBeenCalledWith(999)
        })

        it('should maintain highest offset when recording multiple messages', async () => {
            const wrappedBatch = offsetManager.wrapBatch(mockRecorder)

            // Record messages in non-sequential order
            wrappedBatch.record(createMessage({ partition: 1, offset: 100 }))
            wrappedBatch.record(createMessage({ partition: 1, offset: 99 }))
            wrappedBatch.record(createMessage({ partition: 1, offset: 101 }))

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
