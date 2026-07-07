import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT, PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { PersonOutputs } from '~/ingestion/common/persons/person-context'
import { FlushResult, PersonsStore } from '~/ingestion/common/persons/persons-store'
import {
    batchStoreFlushCacheEntriesHistogram,
    batchStoreFlushDirtyEntriesHistogram,
    batchStoreFlushKafkaMessagesHistogram,
    batchStoreFlushLatencyHistogram,
    batchStoreFlushOperationsCounter,
    batchStoreFlushReferencedBatchesHistogram,
    batchStoreFlushResultRecordsHistogram,
    batchStoreFlushTriggerBatchSizeHistogram,
} from '~/ingestion/common/stores/metrics'
import { AfterBatchInput } from '~/ingestion/framework/batching-pipeline'
import { isOkResult, ok } from '~/ingestion/framework/results'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'

import { FlushBatchStoresStepConfig, createFlushBatchStoresStep } from './flush-batch-stores-step'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn(),
}))

jest.mock('~/ingestion/common/stores/metrics', () => ({
    batchStoreFlushCacheEntriesHistogram: { observe: jest.fn() },
    batchStoreFlushDirtyEntriesHistogram: { observe: jest.fn() },
    batchStoreFlushKafkaMessagesHistogram: { observe: jest.fn() },
    batchStoreFlushLatencyHistogram: { observe: jest.fn() },
    batchStoreFlushOperationsCounter: { inc: jest.fn() },
    batchStoreFlushReferencedBatchesHistogram: { observe: jest.fn() },
    batchStoreFlushResultRecordsHistogram: { observe: jest.fn() },
    batchStoreFlushTriggerBatchSizeHistogram: { observe: jest.fn() },
}))

describe('flush-batch-stores-step', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let mockGroupStore: jest.Mocked<BatchWritingGroupStore>
    let mockOutputs: PersonOutputs
    let storesConfig: FlushBatchStoresStepConfig

    beforeEach(() => {
        mockPersonsStore = {
            getFlushStats: jest.fn(() => ({
                dirtyEntryCount: 0,
                referencedBatchCount: 0,
                cacheEntryCount: 0,
            })),
            flush: jest.fn(),
            shutdown: jest.fn(),
            releaseBatch: jest.fn(),
        } as any

        mockGroupStore = {
            getFlushStats: jest.fn(() => ({
                dirtyEntryCount: 0,
                referencedBatchCount: 0,
                cacheEntryCount: 0,
            })),
            flush: jest.fn(),
            shutdown: jest.fn(),
            releaseBatch: jest.fn(),
        } as any

        mockOutputs = createMockIngestionOutputs<
            | typeof PERSONS_OUTPUT
            | typeof PERSON_DISTINCT_IDS_OUTPUT
            | typeof INGESTION_WARNINGS_OUTPUT
            | typeof PERSON_MERGE_EVENTS_OUTPUT
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
                teamId: 1,
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

        it('reports flush lifecycle metrics', async () => {
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
                    teamId: 1,
                    distinctId: 'user2',
                    uuid: 'uuid2',
                },
            ]

            mockPersonsStore.getFlushStats.mockReturnValue({
                dirtyEntryCount: 2,
                referencedBatchCount: 2,
                cacheEntryCount: 5,
            })
            mockGroupStore.getFlushStats.mockReturnValue({
                dirtyEntryCount: 1,
                referencedBatchCount: 1,
                cacheEntryCount: 3,
            })
            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])

            await step(makeInput(7))

            expect(batchStoreFlushTriggerBatchSizeHistogram.observe).toHaveBeenCalledWith(7)
            expect(batchStoreFlushDirtyEntriesHistogram.observe).toHaveBeenCalledWith({ store: 'person' }, 2)
            expect(batchStoreFlushDirtyEntriesHistogram.observe).toHaveBeenCalledWith({ store: 'group' }, 1)
            expect(batchStoreFlushReferencedBatchesHistogram.observe).toHaveBeenCalledWith({ store: 'person' }, 2)
            expect(batchStoreFlushReferencedBatchesHistogram.observe).toHaveBeenCalledWith({ store: 'group' }, 1)
            expect(batchStoreFlushCacheEntriesHistogram.observe).toHaveBeenCalledWith({ store: 'person' }, 5)
            expect(batchStoreFlushCacheEntriesHistogram.observe).toHaveBeenCalledWith({ store: 'group' }, 3)
            expect(batchStoreFlushOperationsCounter.inc).toHaveBeenCalledWith({ store: 'person', outcome: 'success' })
            expect(batchStoreFlushOperationsCounter.inc).toHaveBeenCalledWith({ store: 'group', outcome: 'success' })
            expect(batchStoreFlushLatencyHistogram.observe).toHaveBeenCalledWith(
                { store: 'person', outcome: 'success' },
                expect.any(Number)
            )
            expect(batchStoreFlushLatencyHistogram.observe).toHaveBeenCalledWith(
                { store: 'group', outcome: 'success' },
                expect.any(Number)
            )
            expect(batchStoreFlushResultRecordsHistogram.observe).toHaveBeenCalledWith({ store: 'person' }, 2)
            expect(batchStoreFlushResultRecordsHistogram.observe).toHaveBeenCalledWith({ store: 'group' }, 0)
            expect(batchStoreFlushKafkaMessagesHistogram.observe).toHaveBeenCalledWith({ store: 'person' }, 3)
            expect(batchStoreFlushKafkaMessagesHistogram.observe).toHaveBeenCalledWith({ store: 'group' }, 0)
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

            expect(emitIngestionWarning).toHaveBeenCalledWith(mockOutputs, 1, {
                type: 'message_size_too_large',
                details: {
                    eventUuid: 'uuid1',
                    distinctId: 'user1',
                    step: 'flushBatchStoresStep',
                },
                category: 'size',
                severity: 'error',
                pipelineStep: 'flush',
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

        it('calls releaseBatch on both stores with the correct batchId after a successful flush', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const input = makeInput()
            await step(input)

            expect(mockPersonsStore.releaseBatch).toHaveBeenCalledWith(input.batchId)
            expect(mockGroupStore.releaseBatch).toHaveBeenCalledWith(input.batchId)
        })

        it('calls releaseBatch on both stores even when flush throws', async () => {
            mockPersonsStore.flush.mockRejectedValue(new Error('DB error'))
            mockGroupStore.flush.mockResolvedValue([])

            const input = makeInput()
            await expect(step(input)).rejects.toThrow('DB error')

            expect(mockPersonsStore.releaseBatch).toHaveBeenCalledWith(input.batchId)
            expect(mockGroupStore.releaseBatch).toHaveBeenCalledWith(input.batchId)
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
                teamId: 1,
            })
        })

        it('flushes both stores in parallel', async () => {
            const callOrder: string[] = []

            mockPersonsStore.flush.mockImplementation(() => {
                callOrder.push('persons.flush')
                return Promise.resolve([])
            })
            mockGroupStore.flush.mockImplementation(() => {
                callOrder.push('group.flush')
                return Promise.resolve([])
            })

            await step(makeInput())

            expect(callOrder.sort()).toEqual(['group.flush', 'persons.flush'])
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
                teamId: 1,
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
