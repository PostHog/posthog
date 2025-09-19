import { Message } from 'node-rdkafka'

import { AsyncPreprocessingStep, SyncPreprocessingStep } from '../../ingestion/processing-pipeline'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { dlq, drop, redirect, success } from './event-pipeline/pipeline-step-result'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from './pipeline-helpers'
import { BatchResultHandlingPipeline, PipelineConfig, ResultHandlingPipeline } from './result-handling-pipeline'

// Mock the pipeline helpers
jest.mock('./pipeline-helpers', () => ({
    logDroppedMessage: jest.fn(),
    redirectMessageToTopic: jest.fn(),
    sendMessageToDLQ: jest.fn(),
}))

const mockLogDroppedMessage = logDroppedMessage as jest.MockedFunction<typeof logDroppedMessage>
const mockRedirectMessageToTopic = redirectMessageToTopic as jest.MockedFunction<typeof redirectMessageToTopic>
const mockSendMessageToDLQ = sendMessageToDLQ as jest.MockedFunction<typeof sendMessageToDLQ>

describe('ResultHandlingPipeline', () => {
    let mockKafkaProducer: KafkaProducerWrapper
    let mockPromiseScheduler: PromiseScheduler
    let mockMessage: Message
    let config: PipelineConfig

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockPromiseScheduler = {
            schedule: jest.fn(),
        } as unknown as PromiseScheduler

        mockMessage = {
            value: Buffer.from('test message'),
            topic: 'test-topic',
            partition: 0,
            offset: 123,
            key: 'test-key',
            headers: [],
            size: 12,
        } as Message

        config = {
            kafkaProducer: mockKafkaProducer,
            dlqTopic: 'test-dlq',
            promiseScheduler: mockPromiseScheduler,
        }
    })

    describe('static methods', () => {
        it('should create pipeline with success result using of()', async () => {
            const value = { test: 'data' }
            const pipeline = ResultHandlingPipeline.of(value, mockMessage, config)

            const result = await pipeline.unwrap()
            expect(result).toEqual(value)
        })
    })

    describe('pipe() - synchronous steps', () => {
        it('should execute step when result is success', async () => {
            const initialValue = { count: 1 }
            const step: SyncPreprocessingStep<typeof initialValue, { count: number }> = (input) => {
                return success({ count: input.count + 1 })
            }

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config).pipe(step).unwrap()

            expect(result).toEqual({ count: 2 })
        })

        it('should handle drop result and return null', async () => {
            const initialValue = { count: 1 }
            const dropStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return drop('test drop reason')
            }
            const secondStep: SyncPreprocessingStep<{ count: number }, { count: number }> = jest.fn((input) => {
                return success({ count: input.count + 1 })
            })

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipe(dropStep)
                .pipe(secondStep)
                .unwrap()

            expect(result).toBeNull()
            expect(secondStep).not.toHaveBeenCalled()
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(
                mockMessage,
                'test drop reason',
                'pipeline_result_handler'
            )
        })

        it('should handle redirect result and return null', async () => {
            const initialValue = { count: 1 }
            const redirectStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return redirect('test redirect', 'overflow-topic', true, false)
            }
            const secondStep: SyncPreprocessingStep<{ count: number }, { count: number }> = jest.fn((input) => {
                return success({ count: input.count + 1 })
            })

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipe(redirectStep)
                .pipe(secondStep)
                .unwrap()

            expect(result).toBeNull()
            expect(secondStep).not.toHaveBeenCalled()
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                mockMessage,
                'overflow-topic',
                'pipeline_result_handler',
                true,
                false
            )
        })

        it('should handle dlq result and return null', async () => {
            const initialValue = { count: 1 }
            const testError = new Error('test error')
            const dlqStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return dlq('test dlq reason', testError)
            }
            const secondStep: SyncPreprocessingStep<{ count: number }, { count: number }> = jest.fn((input) => {
                return success({ count: input.count + 1 })
            })

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipe(dlqStep)
                .pipe(secondStep)
                .unwrap()

            expect(result).toBeNull()
            expect(secondStep).not.toHaveBeenCalled()
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockMessage,
                testError,
                'pipeline_result_handler',
                'test-dlq'
            )
        })

        it('should handle dlq result without error and create default error', async () => {
            const initialValue = { count: 1 }
            const dlqStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return dlq('test dlq reason')
            }

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config).pipe(dlqStep).unwrap()

            expect(result).toBeNull()
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockMessage,
                expect.any(Error),
                'pipeline_result_handler',
                'test-dlq'
            )

            const errorArg = (mockSendMessageToDLQ as jest.Mock).mock.calls[0][2]
            expect(errorArg.message).toBe('test dlq reason')
        })

        it('should chain multiple synchronous steps successfully', async () => {
            const initialValue = { count: 0 }

            const step1: SyncPreprocessingStep<typeof initialValue, { count: number }> = (input) => {
                return success({ count: input.count + 1 })
            }

            const step2: SyncPreprocessingStep<{ count: number }, { count: number; doubled: number }> = (input) => {
                return success({ count: input.count, doubled: input.count * 2 })
            }

            const step3: SyncPreprocessingStep<{ count: number; doubled: number }, { final: string }> = (input) => {
                return success({ final: `count: ${input.count}, doubled: ${input.doubled}` })
            }

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipe(step1)
                .pipe(step2)
                .pipe(step3)
                .unwrap()

            expect(result).toEqual({ final: 'count: 1, doubled: 2' })
        })
    })

    describe('pipeAsync() - mixed sync/async steps', () => {
        it('should execute async step and return result', async () => {
            const initialValue = { count: 1 }
            const asyncStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipeAsync(asyncStep)
                .unwrap()
            expect(result).toEqual({ count: 2 })
        })

        it('should not execute async step when sync result is failure', async () => {
            const initialValue = { count: 1 }
            const dropStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return drop('initial drop')
            }
            const asyncStep: AsyncPreprocessingStep<{ count: number }, { executed: boolean }> = jest.fn(async () => {
                await Promise.resolve()
                return success({ executed: true })
            })

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipe(dropStep)
                .pipeAsync(asyncStep)
                .unwrap()

            expect(result).toBeNull()
            expect(asyncStep).not.toHaveBeenCalled()
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(
                mockMessage,
                'initial drop',
                'async_pipeline_result_handler'
            )
        })
    })

    describe('redirect result with default parameters', () => {
        it('should use default preserveKey and awaitAck when not specified', async () => {
            const initialValue = { count: 1 }
            const redirectStep: SyncPreprocessingStep<typeof initialValue, { count: number }> = () => {
                return redirect('test redirect', 'overflow-topic')
            }

            const result = await ResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipe(redirectStep)
                .unwrap()

            expect(result).toBeNull()
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                mockMessage,
                'overflow-topic',
                'pipeline_result_handler',
                true, // default preserveKey
                true // default awaitAck
            )
        })
    })
})

describe('BatchResultHandlingPipeline', () => {
    let mockKafkaProducer: KafkaProducerWrapper
    let mockPromiseScheduler: PromiseScheduler
    let mockMessages: Message[]
    let config: PipelineConfig

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockPromiseScheduler = {
            schedule: jest.fn(),
        } as unknown as PromiseScheduler

        mockMessages = [
            {
                value: Buffer.from('test message 1'),
                topic: 'test-topic',
                partition: 0,
                offset: 123,
                key: 'test-key-1',
                headers: [],
                size: 14,
            } as Message,
            {
                value: Buffer.from('test message 2'),
                topic: 'test-topic',
                partition: 0,
                offset: 124,
                key: 'test-key-2',
                headers: [],
                size: 14,
            } as Message,
        ]

        config = {
            kafkaProducer: mockKafkaProducer,
            dlqTopic: 'test-dlq',
            promiseScheduler: mockPromiseScheduler,
        }
    })

    describe('static methods', () => {
        it('should create batch result handling pipeline using of()', async () => {
            const { BatchProcessingPipeline } = await import('../../ingestion/batch-processing-pipeline')
            const values = [{ test: 'data1' }, { test: 'data2' }]

            const pipeline = BatchResultHandlingPipeline.of(BatchProcessingPipeline.of(values), mockMessages, config)

            const result = await pipeline.unwrap()
            expect(result).toEqual([{ test: 'data1' }, { test: 'data2' }])
        })
    })

    describe('pipe() - batch operations with result handling', () => {
        it('should execute batch step and filter successful results', async () => {
            const { BatchProcessingPipeline } = await import('../../ingestion/batch-processing-pipeline')
            const values = [{ count: 1 }, { count: 2 }]

            const innerPipeline = BatchProcessingPipeline.of(values).pipe((items) =>
                Promise.resolve(items.map((item) => success({ count: item.count * 2 })))
            )

            const result = await BatchResultHandlingPipeline.of(innerPipeline, mockMessages, config).unwrap()

            expect(result).toEqual([{ count: 2 }, { count: 4 }])
        })

        it('should handle mixed results and filter out non-success', async () => {
            const { BatchProcessingPipeline } = await import('../../ingestion/batch-processing-pipeline')
            const values = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]

            const innerPipeline = BatchProcessingPipeline.of(values).pipe((items) => {
                return Promise.resolve(
                    items.map((item) => {
                        switch (item.id) {
                            case 1:
                                return success({ processed: item.id })
                            case 2:
                                return drop('item 2 dropped')
                            case 3:
                                return redirect('item 3 redirected', 'overflow-topic')
                            case 4:
                                return dlq('item 4 failed', new Error('processing error'))
                            default:
                                return success({ processed: item.id })
                        }
                    })
                )
            })

            const result = await BatchResultHandlingPipeline.of(innerPipeline, mockMessages, config).unwrap()

            expect(result).toEqual([{ processed: 1 }])

            // Verify that non-success results were handled
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(
                mockMessages[1],
                'item 2 dropped',
                'batch_pipeline_result_handler'
            )
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                mockMessages[2] || mockMessages[0],
                'overflow-topic',
                'batch_pipeline_result_handler',
                true,
                true
            )
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockMessages[3] || mockMessages[0],
                expect.any(Error),
                'batch_pipeline_result_handler',
                'test-dlq'
            )
        })
    })

    describe('pipeConcurrently() - concurrent processing with result handling', () => {
        it('should process items concurrently and filter successful results', async () => {
            const { BatchProcessingPipeline } = await import('../../ingestion/batch-processing-pipeline')
            const values = [{ count: 1 }, { count: 2 }, { count: 3 }]

            const innerPipeline = BatchProcessingPipeline.of(values).pipeConcurrently(async (item) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: item.count * 2 })
            })

            const result = await BatchResultHandlingPipeline.of(innerPipeline, mockMessages, config).unwrap()

            expect(result).toEqual([{ count: 2 }, { count: 4 }, { count: 6 }])
        })

        it('should handle concurrent processing failures', async () => {
            const { BatchProcessingPipeline } = await import('../../ingestion/batch-processing-pipeline')
            const values = [{ id: 1 }, { id: 2 }, { id: 3 }]

            const innerPipeline = BatchProcessingPipeline.of(values).pipeConcurrently((item) => {
                if (item.id === 2) {
                    return Promise.resolve(drop('item 2 dropped'))
                }
                return Promise.resolve(success({ processed: item.id }))
            })

            const result = await BatchResultHandlingPipeline.of(innerPipeline, mockMessages, config).unwrap()

            expect(result).toEqual([{ processed: 1 }, { processed: 3 }])
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(
                mockMessages[1],
                'item 2 dropped',
                'batch_pipeline_result_handler'
            )
        })
    })

    describe('message fallback handling', () => {
        it('should handle cases where there are fewer messages than results', async () => {
            const { BatchProcessingPipeline } = await import('../../ingestion/batch-processing-pipeline')
            const values = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }] // More values than messages

            const innerPipeline = BatchProcessingPipeline.of(values).pipe((items) => {
                return Promise.resolve(
                    items.map((item, index) => {
                        if (index >= 2) {
                            return drop(`item ${item.id} dropped`)
                        }
                        return success({ processed: item.id })
                    })
                )
            })

            const result = await BatchResultHandlingPipeline.of(innerPipeline, mockMessages, config).unwrap()

            expect(result).toEqual([{ processed: 1 }, { processed: 2 }])

            // Should fallback to first message for items without corresponding messages
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(
                mockMessages[0], // Fallback message
                'item 3 dropped',
                'batch_pipeline_result_handler'
            )
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(
                mockMessages[0], // Fallback message
                'item 4 dropped',
                'batch_pipeline_result_handler'
            )
        })
    })
})

describe('Integration tests', () => {
    let mockKafkaProducer: KafkaProducerWrapper
    let mockPromiseScheduler: PromiseScheduler
    let mockMessage: Message
    let config: PipelineConfig

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            producer: {} as any,
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockPromiseScheduler = {
            schedule: jest.fn(),
        } as unknown as PromiseScheduler

        mockMessage = {
            value: Buffer.from('test message'),
            topic: 'test-topic',
            partition: 0,
            offset: 123,
            key: 'test-key',
            headers: [],
            size: 12,
        } as Message

        config = {
            kafkaProducer: mockKafkaProducer,
            dlqTopic: 'test-dlq',
            promiseScheduler: mockPromiseScheduler,
        }
    })

    it('should handle realistic event processing pipeline', async () => {
        interface EventInput {
            rawEvent: string
        }

        interface ParsedEvent {
            eventType: string
            userId: string
        }

        interface ValidatedEvent extends ParsedEvent {
            isValid: boolean
        }

        interface ProcessedEvent extends ValidatedEvent {
            timestamp: string
        }

        const parseStep: SyncPreprocessingStep<EventInput, ParsedEvent> = (input) => {
            if (input.rawEvent === 'invalid') {
                return drop('Invalid event format')
            }
            return success({
                eventType: 'pageview',
                userId: 'user123',
            })
        }

        const validateStep: AsyncPreprocessingStep<ParsedEvent, ValidatedEvent> = async (input) => {
            await new Promise((resolve) => setTimeout(resolve, 1))
            if (input.userId === 'blocked') {
                return redirect('User blocked', 'blocked-events-topic')
            }
            return success({
                ...input,
                isValid: true,
            })
        }

        const processStep: SyncPreprocessingStep<ValidatedEvent, ProcessedEvent> = (input) => {
            return success({
                ...input,
                timestamp: '2023-01-01T00:00:00Z',
            })
        }

        const result = await ResultHandlingPipeline.of({ rawEvent: 'test-event' }, mockMessage, config)
            .pipe(parseStep)
            .pipeAsync(validateStep)
            .pipe(processStep)
            .unwrap()

        expect(result).toEqual({
            eventType: 'pageview',
            userId: 'user123',
            isValid: true,
            timestamp: '2023-01-01T00:00:00Z',
        })
    })

    it('should handle pipeline failure at different stages', async () => {
        const parseStep: SyncPreprocessingStep<{ rawEvent: string }, { parsed: boolean }> = () => {
            return success({ parsed: true })
        }

        const validateStep: AsyncPreprocessingStep<{ parsed: boolean }, { validated: boolean }> = async () => {
            await Promise.resolve()
            return dlq('Validation failed', new Error('Invalid data'))
        }

        const processStep: SyncPreprocessingStep<{ validated: boolean }, { processed: boolean }> = jest.fn(() => {
            return success({ processed: true })
        })

        const result = await ResultHandlingPipeline.of({ rawEvent: 'test' }, mockMessage, config)
            .pipe(parseStep)
            .pipeAsync(validateStep)
            .pipe(processStep)
            .unwrap()

        expect(result).toBeNull()
        expect(processStep).not.toHaveBeenCalled()
        expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
            mockKafkaProducer,
            mockMessage,
            expect.any(Error),
            'async_pipeline_result_handler',
            'test-dlq'
        )
    })
})
