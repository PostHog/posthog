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
        } as unknown as jest.Mocked<SessionBatchRecorder>

        offsetManager = new KafkaOffsetManager(mockCommitOffsets, TEST_TOPIC)
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
})
