import { MessageSizeTooLarge } from '../../utils/db/error'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonOutputs } from '../../worker/ingestion/persons/person-context'
import { FlushResult, PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT } from '../analytics/outputs'
import { emitIngestionWarning } from '../common/ingestion-warnings'
import { INGESTION_WARNINGS_OUTPUT } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineResultType } from '../pipelines/results'
import { createFlushBatchStoresStep } from './flush-batch-stores-step'

jest.mock('../common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn(),
}))

describe('flush-batch-stores-step', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let mockGroupStore: jest.Mocked<BatchWritingGroupStore>
    let mockOutputs: PersonOutputs

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

        const mockProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
        } as any
        mockOutputs = new IngestionOutputs({
            [PERSONS_OUTPUT]: { topic: 'person_updates', producer: mockProducer },
            [PERSON_DISTINCT_IDS_OUTPUT]: { topic: 'person_distinct_ids', producer: mockProducer },
            [INGESTION_WARNINGS_OUTPUT]: { topic: 'ingestion_warnings', producer: mockProducer },
        })

        jest.clearAllMocks()
    })

    describe('createFlushBatchStoresStep', () => {
        it('should flush both stores in parallel', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const batch = [{ id: 1 }, { id: 2 }]
            await step(batch)

            expect(mockPersonsStore.flush).toHaveBeenCalledTimes(1)
            expect(mockGroupStore.flush).toHaveBeenCalledTimes(1)
        })

        it('should report batch metrics after flushing', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await step([{ id: 1 }])

            expect(mockPersonsStore.reportBatch).toHaveBeenCalledTimes(1)
            expect(mockGroupStore.reportBatch).toHaveBeenCalledTimes(1)
        })

        it('should reset both stores after flushing', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await step([{ id: 1 }])

            expect(mockPersonsStore.reset).toHaveBeenCalledTimes(1)
            expect(mockGroupStore.reset).toHaveBeenCalledTimes(1)
        })

        it('should create produce promises for person store messages', async () => {
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

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const results = await step([{ id: 1 }])

            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: Buffer.from('value1'),
            })

            expect(results).toHaveLength(1)
            expect(results[0].type).toBe(PipelineResultType.OK)
            expect(results[0].sideEffects).toHaveLength(1)
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

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const results = await step([{ id: 1 }])

            expect(produceSpy).toHaveBeenCalledTimes(2)
            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: Buffer.from('value1'),
            })
            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: Buffer.from('value2'),
            })
            expect(results[0].sideEffects).toHaveLength(2)
        })

        it('should return same number of results as batch size', async () => {
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockResolvedValue([])

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const batch = [{ id: 1 }, { id: 2 }, { id: 3 }]
            const results = await step(batch)

            expect(results).toHaveLength(3)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('should handle empty batch', async () => {
            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const results = await step([])

            expect(results).toHaveLength(0)
            expect(mockPersonsStore.flush).not.toHaveBeenCalled()
            expect(mockGroupStore.flush).not.toHaveBeenCalled()
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

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const results = await step([{ id: 1 }])

            expect(emitIngestionWarning).toHaveBeenCalledWith(mockOutputs, 1, 'message_size_too_large', {
                eventUuid: 'uuid1',
                distinctId: 'user1',
                step: 'flushBatchStoresStep',
            })

            expect(results).toHaveLength(1)
            expect(results[0].type).toBe(PipelineResultType.OK)
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

            const produceError = new Error('Kafka connection failed')
            jest.spyOn(mockOutputs, 'produce').mockRejectedValue(produceError)

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const results = await step([{ id: 1 }])

            // Error should be in the side effect promise
            expect(results[0].sideEffects).toHaveLength(1)
            await expect(results[0].sideEffects[0]).rejects.toThrow('Kafka connection failed')
        })

        it('should throw if person store flush fails', async () => {
            const flushError = new Error('Database connection failed')
            mockPersonsStore.flush.mockRejectedValue(flushError)
            mockGroupStore.flush.mockResolvedValue([])

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await expect(step([{ id: 1 }])).rejects.toThrow('Database connection failed')
        })

        it('should throw if group store flush fails', async () => {
            const flushError = new Error('Database connection failed')
            mockPersonsStore.flush.mockResolvedValue([])
            mockGroupStore.flush.mockRejectedValue(flushError)

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await expect(step([{ id: 1 }])).rejects.toThrow('Database connection failed')
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

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await step([{ id: 1 }])

            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: null,
            })
        })

        it('should attach side effects only to first batch item to avoid duplication', async () => {
            const personMessages: FlushResult[] = [
                {
                    messages: [{ output: PERSONS_OUTPUT, value: Buffer.from('value1') }],
                    teamId: 1,
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const batch = [{ id: 1 }, { id: 2 }, { id: 3 }]
            const results = await step(batch)

            // Only the first result should have side effects to avoid duplication
            expect(results).toHaveLength(3)
            expect(results[0].sideEffects).toHaveLength(1)
            expect(results[1].sideEffects).toHaveLength(0)
            expect(results[2].sideEffects).toHaveLength(0)
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

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await step([{ id: 1 }])

            // Flushes happen in parallel, so order between them doesn't matter
            // But reportBatch and reset must happen after flush
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

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await step([{ id: 1 }])

            expect(produceSpy).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: Buffer.from('string-value'),
            })
        })

        it('should handle multiple flush results with multiple messages each', async () => {
            const personMessages: FlushResult[] = [
                {
                    messages: [
                        { output: PERSONS_OUTPUT, value: Buffer.from('value1') },
                        { output: PERSONS_OUTPUT, value: Buffer.from('value2') },
                    ],
                    teamId: 1,
                },
                {
                    messages: [{ output: PERSON_DISTINCT_IDS_OUTPUT, value: Buffer.from('value3') }],
                    teamId: 2,
                },
            ]

            mockPersonsStore.flush.mockResolvedValue(personMessages)
            mockGroupStore.flush.mockResolvedValue([])
            const produceSpy = jest.spyOn(mockOutputs, 'produce')

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            const results = await step([{ id: 1 }])

            expect(produceSpy).toHaveBeenCalledTimes(3)
            expect(results[0].sideEffects).toHaveLength(3)
        })

        it('should not reset or report if flush fails', async () => {
            mockPersonsStore.flush.mockRejectedValue(new Error('DB error'))
            mockGroupStore.flush.mockResolvedValue([])

            const step = createFlushBatchStoresStep({
                personsStore: mockPersonsStore,
                groupStore: mockGroupStore,
                outputs: mockOutputs,
            })

            await expect(step([{ id: 1 }])).rejects.toThrow('DB error')

            expect(mockPersonsStore.reportBatch).not.toHaveBeenCalled()
            expect(mockGroupStore.reportBatch).not.toHaveBeenCalled()
            expect(mockPersonsStore.reset).not.toHaveBeenCalled()
            expect(mockGroupStore.reset).not.toHaveBeenCalled()
        })
    })
})
