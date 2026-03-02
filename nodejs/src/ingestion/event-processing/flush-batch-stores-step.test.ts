import { KafkaProducerWrapper } from '../../kafka/producer'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { AfterBatchInput } from '../pipelines/batching-pipeline'
import { isOkResult, ok } from '../pipelines/results'
import { BatchStores, createFlushBatchStoresStep, createSetBatchStoresStep } from './flush-batch-stores-step'

jest.mock('../../worker/ingestion/utils', () => ({
    captureIngestionWarning: jest.fn(),
}))

describe('flush-batch-stores-step', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let mockGroupStore: jest.Mocked<BatchWritingGroupStore>
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let storesConfig: BatchStores

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

        storesConfig = {
            personsStore: mockPersonsStore,
            groupStore: mockGroupStore,
            kafkaProducer: mockKafkaProducer,
        }

        jest.clearAllMocks()
    })

    describe('createSetBatchStoresStep', () => {
        it('should store config in batchContext and add stores to element values', async () => {
            const elements = [
                { result: ok({ value: 'el-1' }), context: { sideEffects: [], warnings: [] } },
                { result: ok({ value: 'el-2' }), context: { sideEffects: [], warnings: [] } },
            ]
            const step = createSetBatchStoresStep<{ value: string }, any>(storesConfig)
            const result = await step({ elements: elements as any, batchId: 0 })

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.batchContext).toBe(storesConfig)
                expect(result.value.elements).toHaveLength(2)

                const el0 = result.value.elements[0].result
                const el1 = result.value.elements[1].result
                expect(isOkResult(el0)).toBe(true)
                expect(isOkResult(el1)).toBe(true)
                if (isOkResult(el0) && isOkResult(el1)) {
                    expect(el0.value.value).toBe('el-1')
                    expect(el0.value.personsStore).toBe(mockPersonsStore)
                    expect(el1.value.value).toBe('el-2')
                    expect(el1.value.groupStore).toBe(mockGroupStore)
                }
            }
        })
    })

    describe('createFlushBatchStoresStep', () => {
        let step: ReturnType<typeof createFlushBatchStoresStep>

        function makeInput(): AfterBatchInput<void, any, BatchStores> {
            return {
                elements: [],
                batchContext: storesConfig,
                batchId: 0,
            }
        }

        beforeEach(() => {
            step = createFlushBatchStoresStep()
        })

        it('should flush both stores in parallel', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            await step(makeInput())

            expect(mockPersonsStore.flush).toHaveBeenCalledTimes(1)
            expect(mockGroupStore.flush).toHaveBeenCalledTimes(1)
        })

        it('should report batch metrics after flushing', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            await step(makeInput())

            expect(mockPersonsStore.reportBatch).toHaveBeenCalledTimes(1)
            expect(mockGroupStore.reportBatch).toHaveBeenCalledTimes(1)
        })

        it('should reset both stores after flushing', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            await step(makeInput())

            expect(mockPersonsStore.reset).toHaveBeenCalledTimes(1)
            expect(mockGroupStore.reset).toHaveBeenCalledTimes(1)
        })

        it('should return ok result with produce promises as side effects', async () => {
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

            const result = await step(makeInput())

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(1)
            }
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

            const result = await step(makeInput())

            expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(2)
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(2)
            }
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

            const result = await step(makeInput())

            expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(3)
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(3)
            }
        })

        it('should return empty side effects when no messages to produce', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const result = await step(makeInput())

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(0)
            }
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

            const result = await step(makeInput())

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(1)
                await result.sideEffects[0]
            }

            expect(captureIngestionWarning).toHaveBeenCalledWith(mockKafkaProducer, 1, 'message_size_too_large', {
                eventUuid: 'uuid1',
                distinctId: 'user1',
                step: 'flushBatchStoresStep',
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

            const result = await step(makeInput())

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(1)
                await expect(result.sideEffects[0]).rejects.toThrow('Kafka connection failed')
            }
        })

        it('should throw if person store flush fails', async () => {
            mockPersonsStore.flush.mockRejectedValue(new Error('Database connection failed'))
            mockGroupStore.flush.mockResolvedValue([])

            await expect(step(makeInput())).rejects.toThrow('Database connection failed')
        })

        it('should throw if group store flush fails', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockRejectedValue(new Error('Database connection failed'))

            await expect(step(makeInput())).rejects.toThrow('Database connection failed')
        })

        it('should not reset or report if flush fails', async () => {
            mockPersonsStore.flush.mockRejectedValue(new Error('DB error'))
            mockGroupStore.flush.mockResolvedValue([])

            await expect(step(makeInput())).rejects.toThrow('DB error')

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

            await step(makeInput())

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

            await step(makeInput())

            expect(callOrder.slice(0, 2).sort()).toEqual(['group.flush', 'persons.flush'])
            expect(callOrder.slice(2)).toEqual([
                'persons.reportBatch',
                'group.reportBatch',
                'persons.reset',
                'group.reset',
            ])
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

            await step(makeInput())

            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'person_updates',
                key: Buffer.from('string-key'),
                value: Buffer.from('string-value'),
                headers: { header1: 'value1' },
            })
        })

        it('should pass through elements and batchContext in the result', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const input = makeInput()
            input.elements = [{ result: 'test-element' }] as any
            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.elements).toEqual([{ result: 'test-element' }])
                expect(result.value.batchContext).toBe(input.batchContext)
            }
        })
    })
})
