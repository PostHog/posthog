import { Message } from 'node-rdkafka'

import { AsyncPreprocessingStep, SyncPreprocessingStep } from '../../ingestion/processing-pipeline'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { dlq, drop, redirect, success } from './event-pipeline/pipeline-step-result'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from './pipeline-helpers'
import { AsyncResultHandlingPipeline, PipelineConfig, ResultHandlingPipeline } from './result-handling-pipeline'

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
        it('should transition to AsyncResultHandlingPipeline', async () => {
            const initialValue = { count: 1 }
            const asyncStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }

            const asyncPipeline = ResultHandlingPipeline.of(initialValue, mockMessage, config).pipeAsync(asyncStep)
            expect(asyncPipeline).toBeInstanceOf(AsyncResultHandlingPipeline)

            const result = await asyncPipeline.unwrap()
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

describe('AsyncResultHandlingPipeline', () => {
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
        it('should create async pipeline using of()', async () => {
            const value = { test: 'data' }
            const pipeline = AsyncResultHandlingPipeline.of(value, mockMessage, config)

            const result = await pipeline.unwrap()
            expect(result).toEqual(value)
        })
    })

    describe('pipe() - synchronous steps on async pipeline', () => {
        it('should execute sync step after async step', async () => {
            const initialValue = { count: 1 }
            const asyncStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }
            const syncStep: SyncPreprocessingStep<{ count: number }, { count: number; final: boolean }> = (input) => {
                return success({ count: input.count, final: true })
            }

            const result = await AsyncResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipeAsync(asyncStep)
                .pipe(syncStep)
                .unwrap()

            expect(result).toEqual({ count: 2, final: true })
        })

        it('should skip sync step when async result is failure', async () => {
            const initialValue = { count: 1 }
            const asyncStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async () => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return drop('async drop')
            }
            const syncStep: SyncPreprocessingStep<{ count: number }, { final: boolean }> = jest.fn((_input) => {
                return success({ final: true })
            })

            const result = await AsyncResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipeAsync(asyncStep)
                .pipe(syncStep)
                .unwrap()

            expect(result).toBeNull()
            expect(syncStep).not.toHaveBeenCalled()
            expect(mockLogDroppedMessage).toHaveBeenCalledWith(
                mockMessage,
                'async drop',
                'async_pipeline_result_handler'
            )
        })
    })

    describe('pipeAsync() - chaining async steps', () => {
        it('should chain multiple async steps', async () => {
            const initialValue = { count: 0 }

            const step1: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }

            const step2: AsyncPreprocessingStep<{ count: number }, { count: number; doubled: number }> = async (
                input
            ) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count, doubled: input.count * 2 })
            }

            const result = await AsyncResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipeAsync(step1)
                .pipeAsync(step2)
                .unwrap()

            expect(result).toEqual({ count: 1, doubled: 2 })
        })

        it('should stop chain when async step returns failure', async () => {
            const initialValue = { count: 0 }

            const step1: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: input.count + 1 })
            }

            const step2: AsyncPreprocessingStep<{ count: number }, { count: number }> = async () => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return redirect('async redirect', 'overflow-topic', false, true)
            }

            const step3: AsyncPreprocessingStep<{ count: number }, { final: string }> = jest.fn(async (input) => {
                await Promise.resolve()
                return success({ final: `count: ${input.count}` })
            })

            const result = await AsyncResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipeAsync(step1)
                .pipeAsync(step2)
                .pipeAsync(step3)
                .unwrap()

            expect(result).toBeNull()
            expect(step3).not.toHaveBeenCalled()
            expect(mockRedirectMessageToTopic).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockPromiseScheduler,
                mockMessage,
                'overflow-topic',
                'async_pipeline_result_handler',
                false,
                true
            )
        })

        it('should handle async dlq result', async () => {
            const initialValue = { count: 1 }
            const testError = new Error('async error')
            const dlqStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async () => {
                await Promise.resolve()
                return dlq('async dlq reason', testError)
            }

            const result = await AsyncResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipeAsync(dlqStep)
                .unwrap()

            expect(result).toBeNull()
            expect(mockSendMessageToDLQ).toHaveBeenCalledWith(
                mockKafkaProducer,
                mockMessage,
                testError,
                'async_pipeline_result_handler',
                'test-dlq'
            )
        })
    })

    describe('mixed sync and async steps', () => {
        it('should handle complex pipeline with mixed step types', async () => {
            const initialValue = { value: 'start' }

            const syncStep1: SyncPreprocessingStep<typeof initialValue, { value: string; step1: boolean }> = (
                input
            ) => {
                return success({ value: input.value + '-sync1', step1: true })
            }

            const asyncStep1: AsyncPreprocessingStep<
                { value: string; step1: boolean },
                { value: string; step1: boolean; async1: boolean }
            > = async (input) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ ...input, value: input.value + '-async1', async1: true })
            }

            const syncStep2: SyncPreprocessingStep<
                { value: string; step1: boolean; async1: boolean },
                { final: string }
            > = (input) => {
                return success({ final: `${input.value}-sync2` })
            }

            const result = await AsyncResultHandlingPipeline.of(initialValue, mockMessage, config)
                .pipe(syncStep1)
                .pipeAsync(asyncStep1)
                .pipe(syncStep2)
                .unwrap()

            expect(result).toEqual({ final: 'start-sync1-async1-sync2' })
        })
    })

    describe('error handling', () => {
        it('should propagate async step errors', async () => {
            const initialValue = { count: 1 }
            const errorStep: AsyncPreprocessingStep<typeof initialValue, { count: number }> = async () => {
                await Promise.resolve()
                throw new Error('Async step failed')
            }

            await expect(
                AsyncResultHandlingPipeline.of(initialValue, mockMessage, config).pipeAsync(errorStep).unwrap()
            ).rejects.toThrow('Async step failed')
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
