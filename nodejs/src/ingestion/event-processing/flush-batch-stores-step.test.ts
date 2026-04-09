import { createMockIngestionOutputs } from '../../../tests/helpers/mock-ingestion-outputs'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonOutputs } from '../../worker/ingestion/persons/person-context'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT } from '../analytics/outputs'
import { emitIngestionWarning } from '../common/ingestion-warnings'
import { INGESTION_WARNINGS_OUTPUT } from '../common/outputs'
import { AfterBatchInput } from '../pipelines/batching-pipeline'
import { isOkResult, ok } from '../pipelines/results'
import { FlushBatchStoresStepConfig, createFlushBatchStoresStep } from './flush-batch-stores-step'

jest.mock('../common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn(),
}))

describe('flush-batch-stores-step', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let mockGroupStore: jest.Mocked<BatchWritingGroupStore>
    let mockOutputs: PersonOutputs
    let storesConfig: FlushBatchStoresStepConfig

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

        mockOutputs = createMockIngestionOutputs<
            typeof PERSONS_OUTPUT | typeof PERSON_DISTINCT_IDS_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT
        >()

        storesConfig = {
            personsStore: mockPersonsStore,
            groupStore: mockGroupStore,
            outputs: mockOutputs,
        }

        jest.clearAllMocks()
    })

    describe('createFlushBatchStoresStep', () => {
        let step: ReturnType<typeof createFlushBatchStoresStep>

        function makeInput(elementCount = 2): AfterBatchInput<void, any, NonNullable<unknown>> {
            return {
                elements: Array.from({ length: elementCount }, () => ({
                    result: ok(undefined),
                    context: { sideEffects: [], warnings: [] },
                })),
                batchContext: {},
                batchId: 0,
            }
        }

        beforeEach(() => {
            step = createFlushBatchStoresStep(storesConfig)
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
                    messages: [
                        {
                            output: PERSONS_OUTPUT,
                            value: Buffer.from('value1'),
                        },
                    ],
                    teamId: 1,
                    distinctId: 'user1',
                    uuid: 'uuid1',
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            const produceSpy = jest.spyOn(mockOutputs, 'produce')

            const result = await step(makeInput())

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(1)
            }
            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: Buffer.from('value1'),
            })
        })

        it('should handle multiple messages per flush result', async () => {
            const personMessages: FlushResult[] = [
                {
                    messages: [
                        { output: PERSONS_OUTPUT, value: Buffer.from('value1') },
                        { output: PERSONS_OUTPUT, value: Buffer.from('value2') },
                    ],
                    teamId: 1,
                    distinctId: 'user1',
                    uuid: 'uuid1',
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            const produceSpy = jest.spyOn(mockOutputs, 'produce')

            const result = await step(makeInput())

            expect(produceSpy).toHaveBeenCalledTimes(2)
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(2)
            }
        })

        it('should handle multiple flush results with multiple messages each', async () => {
            const personMessages: FlushResult[] = [
                {
                    messages: [
                        { output: PERSONS_OUTPUT, value: Buffer.from('value1') },
                        { output: PERSONS_OUTPUT, value: Buffer.from('value2') },
                    ],
                    teamId: 1,
                    distinctId: 'user1',
                    uuid: 'uuid1',
                },
                {
                    messages: [{ output: PERSON_DISTINCT_IDS_OUTPUT, value: Buffer.from('value3') }],
                    teamId: 2,
                    distinctId: 'user2',
                    uuid: 'uuid2',
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            const produceSpy = jest.spyOn(mockOutputs, 'produce')

            const result = await step(makeInput())

            expect(produceSpy).toHaveBeenCalledTimes(3)
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
                    messages: [{ output: PERSONS_OUTPUT, value: Buffer.from('value1') }],
                    teamId: 1,
                    distinctId: 'user1',
                    uuid: 'uuid1',
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            jest.spyOn(mockOutputs, 'produce').mockRejectedValue(
                new MessageSizeTooLarge('test', new Error('too large'))
            )

            const result = await step(makeInput())

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.sideEffects).toHaveLength(1)
                await result.sideEffects[0]
            }

            expect(emitIngestionWarning).toHaveBeenCalledWith(mockOutputs, 1, 'message_size_too_large', {
                eventUuid: 'uuid1',
                distinctId: 'user1',
                step: 'flushBatchStoresStep',
            })
        })

        it('should propagate other Kafka produce errors', async () => {
            const personMessages: FlushResult[] = [
                {
                    messages: [{ output: PERSONS_OUTPUT, value: Buffer.from('value1') }],
                    teamId: 1,
                    distinctId: 'user1',
                    uuid: 'uuid1',
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            jest.spyOn(mockOutputs, 'produce').mockRejectedValue(new Error('Kafka connection failed'))

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

        it('should handle null values in messages', async () => {
            const personMessages: FlushResult[] = [
                {
                    messages: [{ output: PERSONS_OUTPUT, value: null }],
                    teamId: 1,
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            const produceSpy = jest.spyOn(mockOutputs, 'produce')

            await step(makeInput())

            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: null,
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
                    messages: [
                        {
                            output: PERSONS_OUTPUT,
                            value: Buffer.from('string-value'),
                        },
                    ],
                    teamId: 1,
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            const produceSpy = jest.spyOn(mockOutputs, 'produce')

            await step(makeInput())

            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: Buffer.from('string-value'),
            })
        })

        it('should pass through elements and batchContext in the result', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const input = makeInput(3)
            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.elements).toHaveLength(3)
                expect(result.value.elements).toBe(input.elements)
                expect(result.value.batchContext).toBe(input.batchContext)
            }
        })
    })
})
