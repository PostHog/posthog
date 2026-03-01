import { KafkaProducerWrapper } from '../../kafka/producer'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { FlushBatchStoresStepConfig, flushBatchStores } from './flush-batch-stores-step'

jest.mock('../../worker/ingestion/utils', () => ({
    captureIngestionWarning: jest.fn(),
}))

describe('flushBatchStores', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let mockGroupStore: jest.Mocked<BatchWritingGroupStore>
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let config: FlushBatchStoresStepConfig

    beforeEach(() => {
        mockPersonsStore = {
            flush: jest.fn(),
            reportBatch: jest.fn(),
            reset: jest.fn(),
        } as any

        mockGroupStore = {
            flush: jest.fn(),
            reportBatch: jest.fn(),
            reset: jest.fn(),
        } as any

        mockKafkaProducer = {
            produce: jest.fn(),
        } as any

        config = {
            personsStore: mockPersonsStore,
            groupStore: mockGroupStore,
            kafkaProducer: mockKafkaProducer,
        }

        jest.clearAllMocks()
    })

    it('should flush both stores in parallel', async () => {
        mockPersonsStore.flush.mockResolvedValue([])
        mockGroupStore.flush.mockResolvedValue([])

        await flushBatchStores(config)

        expect(mockPersonsStore.flush).toHaveBeenCalledTimes(1)
        expect(mockGroupStore.flush).toHaveBeenCalledTimes(1)
    })

    it('should report batch metrics after flushing', async () => {
        mockPersonsStore.flush.mockResolvedValue([])
        mockGroupStore.flush.mockResolvedValue([])

        await flushBatchStores(config)

        expect(mockPersonsStore.reportBatch).toHaveBeenCalledTimes(1)
        expect(mockGroupStore.reportBatch).toHaveBeenCalledTimes(1)
    })

    it('should reset both stores after flushing', async () => {
        mockPersonsStore.flush.mockResolvedValue([])
        mockGroupStore.flush.mockResolvedValue([])

        await flushBatchStores(config)

        expect(mockPersonsStore.reset).toHaveBeenCalledTimes(1)
        expect(mockGroupStore.reset).toHaveBeenCalledTimes(1)
    })

    it('should return undefined value and produce promises as side effects', async () => {
        const personMessages: FlushResult[] = [
            {
                topicMessage: {
                    topic: 'person_updates',
                    messages: [{ key: 'key1', value: 'value1', headers: {} }],
                },
                teamId: 1,
                distinctId: 'user1',
                uuid: 'uuid1',
            },
        ]

        mockPersonsStore.flush.mockResolvedValue(personMessages)
        mockGroupStore.flush.mockResolvedValue([])
        mockKafkaProducer.produce.mockResolvedValue(undefined as any)

        const result = await flushBatchStores(config)

        expect(result.elements).toBeUndefined()
        expect(result.sideEffects).toHaveLength(1)
        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: 'person_updates',
            key: Buffer.from('key1'),
            value: Buffer.from('value1'),
            headers: {},
        })
    })

    it('should handle multiple messages per flush result', async () => {
        const personMessages: FlushResult[] = [
            {
                topicMessage: {
                    topic: 'person_updates',
                    messages: [
                        { key: 'key1', value: 'value1', headers: {} },
                        { key: 'key2', value: 'value2', headers: {} },
                    ],
                },
                teamId: 1,
                distinctId: 'user1',
                uuid: 'uuid1',
            },
        ]

        mockPersonsStore.flush.mockResolvedValue(personMessages)
        mockGroupStore.flush.mockResolvedValue([])
        mockKafkaProducer.produce.mockResolvedValue(undefined as any)

        const result = await flushBatchStores(config)

        expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(2)
        expect(result.sideEffects).toHaveLength(2)
    })

    it('should handle multiple flush results with multiple messages each', async () => {
        const personMessages: FlushResult[] = [
            {
                topicMessage: {
                    topic: 'person_updates',
                    messages: [
                        { key: 'key1', value: 'value1', headers: {} },
                        { key: 'key2', value: 'value2', headers: {} },
                    ],
                },
                teamId: 1,
            },
            {
                topicMessage: {
                    topic: 'person_distinct_ids',
                    messages: [{ key: 'key3', value: 'value3', headers: {} }],
                },
                teamId: 2,
            },
        ]

        mockPersonsStore.flush.mockResolvedValue(personMessages)
        mockGroupStore.flush.mockResolvedValue([])
        mockKafkaProducer.produce.mockResolvedValue(undefined as any)

        const result = await flushBatchStores(config)

        expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(3)
        expect(result.sideEffects).toHaveLength(3)
    })

    it('should return empty side effects when no messages to produce', async () => {
        mockPersonsStore.flush.mockResolvedValue([])
        mockGroupStore.flush.mockResolvedValue([])

        const result = await flushBatchStores(config)

        expect(result.elements).toBeUndefined()
        expect(result.sideEffects).toHaveLength(0)
    })

    it('should handle MessageSizeTooLarge errors gracefully', async () => {
        const personMessages: FlushResult[] = [
            {
                topicMessage: {
                    topic: 'person_updates',
                    messages: [{ key: 'key1', value: 'value1', headers: {} }],
                },
                teamId: 1,
                distinctId: 'user1',
                uuid: 'uuid1',
            },
        ]

        mockPersonsStore.flush.mockResolvedValue(personMessages)
        mockGroupStore.flush.mockResolvedValue([])
        mockKafkaProducer.produce.mockRejectedValue(new MessageSizeTooLarge('test', new Error('too large')))

        const result = await flushBatchStores(config)

        // Side effect resolves (doesn't throw) because the error is caught
        expect(result.sideEffects).toHaveLength(1)
        await result.sideEffects![0]

        expect(captureIngestionWarning).toHaveBeenCalledWith(mockKafkaProducer, 1, 'message_size_too_large', {
            eventUuid: 'uuid1',
            distinctId: 'user1',
            step: 'flushBatchStores',
        })
    })

    it('should propagate other Kafka produce errors', async () => {
        const personMessages: FlushResult[] = [
            {
                topicMessage: {
                    topic: 'person_updates',
                    messages: [{ key: 'key1', value: 'value1', headers: {} }],
                },
                teamId: 1,
                distinctId: 'user1',
                uuid: 'uuid1',
            },
        ]

        mockPersonsStore.flush.mockResolvedValue(personMessages)
        mockGroupStore.flush.mockResolvedValue([])
        mockKafkaProducer.produce.mockRejectedValue(new Error('Kafka connection failed'))

        const result = await flushBatchStores(config)

        expect(result.sideEffects).toHaveLength(1)
        await expect(result.sideEffects![0]).rejects.toThrow('Kafka connection failed')
    })

    it('should throw if person store flush fails', async () => {
        mockPersonsStore.flush.mockRejectedValue(new Error('Database connection failed'))
        mockGroupStore.flush.mockResolvedValue([])

        await expect(flushBatchStores(config)).rejects.toThrow('Database connection failed')
    })

    it('should throw if group store flush fails', async () => {
        mockPersonsStore.flush.mockResolvedValue([])
        mockGroupStore.flush.mockRejectedValue(new Error('Database connection failed'))

        await expect(flushBatchStores(config)).rejects.toThrow('Database connection failed')
    })

    it('should not reset or report if flush fails', async () => {
        mockPersonsStore.flush.mockRejectedValue(new Error('DB error'))
        mockGroupStore.flush.mockResolvedValue([])

        await expect(flushBatchStores(config)).rejects.toThrow('DB error')

        expect(mockPersonsStore.reportBatch).not.toHaveBeenCalled()
        expect(mockGroupStore.reportBatch).not.toHaveBeenCalled()
        expect(mockPersonsStore.reset).not.toHaveBeenCalled()
        expect(mockGroupStore.reset).not.toHaveBeenCalled()
    })

    it('should handle null keys and values in messages', async () => {
        const personMessages: FlushResult[] = [
            {
                topicMessage: {
                    topic: 'person_updates',
                    messages: [{ key: null, value: null, headers: {} }],
                },
                teamId: 1,
            },
        ]

        mockPersonsStore.flush.mockResolvedValue(personMessages)
        mockGroupStore.flush.mockResolvedValue([])
        mockKafkaProducer.produce.mockResolvedValue(undefined as any)

        await flushBatchStores(config)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: 'person_updates',
            key: null,
            value: null,
            headers: {},
        })
    })

    it('should call lifecycle methods in correct order', async () => {
        const callOrder: string[] = []

        mockPersonsStore.flush.mockImplementation(() => {
            callOrder.push('persons.flush')
            return Promise.resolve([])
        })
        mockGroupStore.flush.mockImplementation(() => {
            callOrder.push('group.flush')
            return Promise.resolve([])
        })
        mockPersonsStore.reportBatch.mockImplementation(() => {
            callOrder.push('persons.reportBatch')
        })
        mockGroupStore.reportBatch.mockImplementation(() => {
            callOrder.push('group.reportBatch')
        })
        mockPersonsStore.reset.mockImplementation(() => {
            callOrder.push('persons.reset')
        })
        mockGroupStore.reset.mockImplementation(() => {
            callOrder.push('group.reset')
        })

        await flushBatchStores(config)

        // Flushes happen in parallel, so order between them doesn't matter
        // But reportBatch and reset must happen after flush
        expect(callOrder.slice(0, 2).sort()).toEqual(['group.flush', 'persons.flush'])
        expect(callOrder.slice(2)).toEqual(['persons.reportBatch', 'group.reportBatch', 'persons.reset', 'group.reset'])
    })

    it('should produce messages with correct Buffer conversion', async () => {
        const personMessages: FlushResult[] = [
            {
                topicMessage: {
                    topic: 'person_updates',
                    messages: [
                        {
                            key: 'string-key',
                            value: 'string-value',
                            headers: { header1: 'value1' },
                        },
                    ],
                },
                teamId: 1,
            },
        ]

        mockPersonsStore.flush.mockResolvedValue(personMessages)
        mockGroupStore.flush.mockResolvedValue([])
        mockKafkaProducer.produce.mockResolvedValue(undefined as any)

        await flushBatchStores(config)

        expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
            topic: 'person_updates',
            key: Buffer.from('string-key'),
            value: Buffer.from('string-value'),
            headers: { header1: 'value1' },
        })
    })
})
