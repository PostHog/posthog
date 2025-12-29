import { Message } from 'node-rdkafka'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { ingestionLagGauge, ingestionLagHistogram } from '../../common/metrics'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, ProjectId, RawKafkaEvent, TimestampFormat } from '../../types'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { castTimestampOrNow } from '../../utils/utils'
import { eventProcessedAndIngestedCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { isOkResult } from '../pipelines/results'
import { EmitEventStepConfig, createEmitEventStep, productTrackHeader } from './emit-event-step'

// Mock the utils module
jest.mock('../../worker/ingestion/utils', () => ({
    captureIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

// Mock the metrics module
jest.mock('../../worker/ingestion/event-pipeline/metrics', () => ({
    eventProcessedAndIngestedCounter: {
        inc: jest.fn(),
    },
}))

// Mock the ingestion lag metrics
jest.mock('~/common/metrics', () => ({
    ingestionLagGauge: {
        labels: jest.fn().mockReturnValue({
            set: jest.fn(),
        }),
    },
    ingestionLagHistogram: {
        labels: jest.fn().mockReturnValue({
            observe: jest.fn(),
        }),
    },
}))

const mockCaptureIngestionWarning = jest.mocked(captureIngestionWarning)
const mockEventProcessedAndIngestedCounter = jest.mocked(eventProcessedAndIngestedCounter)
const mockIngestionLagGauge = jest.mocked(ingestionLagGauge)
const mockIngestionLagHistogram = jest.mocked(ingestionLagHistogram)

describe('emit-event-step', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let config: EmitEventStepConfig
    let mockRawEvent: RawKafkaEvent
    let mockHeaders: EventHeaders
    let mockMessage: Message

    beforeEach(() => {
        mockHeaders = createTestEventHeaders()
        mockMessage = createTestMessage()
        jest.clearAllMocks()

        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
            disconnect: jest.fn().mockResolvedValue(undefined),
        } as any

        config = {
            kafkaProducer: mockKafkaProducer,
            clickhouseJsonEventsTopic: 'clickhouse_events_json',
            groupId: 'test-group-id',
        }

        const testTimestamp = castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ClickHouse)

        mockRawEvent = {
            uuid: 'test-uuid',
            event: 'test-event',
            properties: JSON.stringify({ test: 'property' }),
            timestamp: testTimestamp,
            team_id: 1,
            project_id: 1 as ProjectId,
            distinct_id: 'test-distinct-id',
            elements_chain: '',
            created_at: testTimestamp,
            person_id: 'person-uuid',
            person_properties: JSON.stringify({}),
            person_created_at: testTimestamp,
            person_mode: 'full',
            historical_migration: false,
        }
    })

    describe('createEmitEventStep', () => {
        it('should emit event successfully when eventToEmit is present', async () => {
            const step = createEmitEventStep(config)
            const input = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toBeUndefined()
            }
            expect(result.sideEffects).toHaveLength(1)
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events_json',
                key: 'test-uuid',
                value: Buffer.from(JSON.stringify(mockRawEvent)),
                headers: { productTrack: 'general' },
            })

            // Execute the side effect to test metric increment
            await result.sideEffects[0]
            expect(mockEventProcessedAndIngestedCounter.inc).toHaveBeenCalledTimes(1)
        })

        it('should handle MessageSizeTooLarge error and capture ingestion warning', async () => {
            const messageSizeTooLargeError = new MessageSizeTooLarge('Message too large', new Error('Kafka error'))
            mockKafkaProducer.produce.mockRejectedValue(messageSizeTooLargeError)

            const step = createEmitEventStep(config)
            const input = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toBeUndefined()
            }
            expect(result.sideEffects).toHaveLength(1)

            // Execute the side effect to test error handling
            await result.sideEffects[0]

            expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(mockKafkaProducer, 1, 'message_size_too_large', {
                eventUuid: 'test-uuid',
                distinctId: 'test-distinct-id',
            })
            // Metric should not be incremented when there's an error
            expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
        })

        it('should re-throw non-MessageSizeTooLarge errors', async () => {
            const genericError = new Error('Generic Kafka error')
            mockKafkaProducer.produce.mockRejectedValue(genericError)

            const step = createEmitEventStep(config)
            const input = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            expect(result.sideEffects).toHaveLength(1)

            // Execute the side effect to test error handling
            await expect(result.sideEffects[0]).rejects.toThrow('Generic Kafka error')
            expect(mockCaptureIngestionWarning).not.toHaveBeenCalled()
            // Metric should not be incremented when there's an error
            expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
        })

        it('should serialize event correctly for Kafka', async () => {
            const step = createEmitEventStep(config)
            const input = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

            await step(input)

            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events_json',
                key: 'test-uuid',
                value: Buffer.from(JSON.stringify(mockRawEvent)),
                headers: { productTrack: 'general' },
            })
        })

        it('should use the correct topic from config', async () => {
            const customConfig = {
                ...config,
                clickhouseJsonEventsTopic: 'custom_topic',
            }
            const step = createEmitEventStep(customConfig)
            const input = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

            await step(input)

            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'custom_topic',
                key: 'test-uuid',
                value: Buffer.from(JSON.stringify(mockRawEvent)),
                headers: { productTrack: 'general' },
            })
        })

        it('should handle events with different UUIDs correctly', async () => {
            const step = createEmitEventStep(config)
            const eventWithDifferentUuid = {
                ...mockRawEvent,
                uuid: 'different-uuid',
            }
            const input = { eventToEmit: eventWithDifferentUuid, inputHeaders: mockHeaders, inputMessage: mockMessage }

            await step(input)

            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events_json',
                key: 'different-uuid',
                value: Buffer.from(JSON.stringify(eventWithDifferentUuid)),
                headers: { productTrack: 'general' },
            })
        })

        it('should work with generic input types that have eventToEmit property', async () => {
            interface CustomInput {
                eventToEmit: RawKafkaEvent
                inputHeaders: EventHeaders
                inputMessage: Message
                customProperty: string
                lastStep: string
            }

            const step = createEmitEventStep<CustomInput>(config)
            const input: CustomInput = {
                eventToEmit: mockRawEvent,
                inputHeaders: mockHeaders,
                inputMessage: mockMessage,
                customProperty: 'test',
                lastStep: 'testStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events_json',
                key: 'test-uuid',
                value: Buffer.from(JSON.stringify(mockRawEvent)),
                headers: { productTrack: 'general' },
            })
        })

        it('should work with EventPipelineResult type', async () => {
            interface EventPipelineResult {
                lastStep: string
                eventToEmit: RawKafkaEvent
                inputHeaders: EventHeaders
                inputMessage: Message
                error?: string
            }

            const step = createEmitEventStep<EventPipelineResult>(config)
            const input: EventPipelineResult = {
                lastStep: 'createEventStep',
                eventToEmit: mockRawEvent,
                inputHeaders: mockHeaders,
                inputMessage: mockMessage,
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events_json',
                key: 'test-uuid',
                value: Buffer.from(JSON.stringify(mockRawEvent)),
                headers: { productTrack: 'general' },
            })
        })

        describe('metrics tracking', () => {
            it('should increment eventProcessedAndIngestedCounter when event is successfully emitted', async () => {
                const step = createEmitEventStep(config)
                const input = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                expect(result.sideEffects).toHaveLength(1)

                // Execute the side effect to trigger metric increment
                await result.sideEffects[0]

                expect(mockEventProcessedAndIngestedCounter.inc).toHaveBeenCalledTimes(1)
                expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(1)
            })

            it('should not increment metric when Kafka produce fails', async () => {
                const kafkaError = new Error('Kafka connection failed')
                mockKafkaProducer.produce.mockRejectedValue(kafkaError)

                const step = createEmitEventStep(config)
                const input = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                expect(result.sideEffects).toHaveLength(1)

                // Execute the side effect and expect it to throw
                await expect(result.sideEffects[0]).rejects.toThrow('Kafka connection failed')

                // Metric should not be incremented on failure
                expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
            })

            it('should increment metric only once per successful emit', async () => {
                const step = createEmitEventStep(config)
                const input1 = { eventToEmit: mockRawEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }
                const input2 = {
                    eventToEmit: { ...mockRawEvent, uuid: 'different-uuid' },
                    inputHeaders: mockHeaders,
                    inputMessage: mockMessage,
                }

                // First emit
                const result1 = await step(input1)
                await result1.sideEffects[0]

                // Second emit
                const result2 = await step(input2)
                await result2.sideEffects[0]

                // Metric should be incremented twice, once for each successful emit
                expect(mockEventProcessedAndIngestedCounter.inc).toHaveBeenCalledTimes(2)
                expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(2)
            })
        })

        it('should emit AI events with llma product track header', async () => {
            const aiEvent = { ...mockRawEvent, event: '$ai_generation' }
            const step = createEmitEventStep(config)
            const input = { eventToEmit: aiEvent, inputHeaders: mockHeaders, inputMessage: mockMessage }

            await step(input)

            expect(mockKafkaProducer.produce).toHaveBeenCalledWith({
                topic: 'clickhouse_events_json',
                key: aiEvent.uuid,
                value: Buffer.from(JSON.stringify(aiEvent)),
                headers: { productTrack: 'llma' },
            })
        })
    })

    describe('productTrackHeader', () => {
        it('should return "llma" for AI generation events', () => {
            const aiEvent = { ...mockRawEvent, event: '$ai_generation' }
            expect(productTrackHeader(aiEvent)).toBe('llma')
        })

        it('should return "llma" for AI completion events', () => {
            const aiEvent = { ...mockRawEvent, event: '$ai_completion' }
            expect(productTrackHeader(aiEvent)).toBe('llma')
        })

        it('should return "general" for non-AI events', () => {
            const regularEvent = { ...mockRawEvent, event: '$pageview' }
            expect(productTrackHeader(regularEvent)).toBe('general')
        })

        it('should return "general" for custom events', () => {
            const customEvent = { ...mockRawEvent, event: 'user_signed_up' }
            expect(productTrackHeader(customEvent)).toBe('general')
        })
    })

    describe('ingestion lag metric', () => {
        const FAKE_NOW_MS = 1702654321987 // 2023-12-15T14:32:01.987Z
        let mockSetFn: jest.Mock
        let mockObserveFn: jest.Mock

        const createMessage = (overrides: Partial<Message> = {}): Message => ({
            value: Buffer.from('test-value'),
            key: Buffer.from('test-key'),
            offset: 100,
            partition: 5,
            topic: 'test-topic',
            size: 10,
            ...overrides,
        })

        const createHeaders = (overrides: Partial<EventHeaders> = {}): EventHeaders => ({
            force_disable_person_processing: false,
            historical_migration: false,
            ...overrides,
        })

        beforeEach(() => {
            jest.useFakeTimers()
            jest.setSystemTime(FAKE_NOW_MS)

            mockSetFn = jest.fn()
            mockObserveFn = jest.fn()
            mockIngestionLagGauge.labels.mockReturnValue({ set: mockSetFn } as any)
            mockIngestionLagHistogram.labels.mockReturnValue({ observe: mockObserveFn } as any)
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('should record ingestion lag when inputHeaders.now and inputMessage are present', async () => {
            const captureTime = new Date(FAKE_NOW_MS - 5432) // 5.432 seconds before fake now
            const step = createEmitEventStep(config)
            const input = {
                eventToEmit: mockRawEvent,
                inputHeaders: createHeaders({ now: captureTime }),
                inputMessage: createMessage(),
            }

            await step(input)

            expect(mockIngestionLagGauge.labels).toHaveBeenCalledWith({
                topic: 'test-topic',
                partition: '5',
                groupId: 'test-group-id',
            })
            expect(mockSetFn).toHaveBeenCalledTimes(1)
            expect(mockSetFn).toHaveBeenCalledWith(5432)
        })

        it('should not record ingestion lag when inputHeaders.now is missing', async () => {
            const step = createEmitEventStep(config)
            const input = {
                eventToEmit: mockRawEvent,
                inputHeaders: createHeaders(),
                inputMessage: createMessage(),
            }

            await step(input)

            expect(mockIngestionLagGauge.labels).not.toHaveBeenCalled()
            expect(mockSetFn).not.toHaveBeenCalled()
        })

        it('should not record ingestion lag when inputMessage.topic is undefined', async () => {
            const step = createEmitEventStep(config)
            const input = {
                eventToEmit: mockRawEvent,
                inputHeaders: createHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
                inputMessage: createMessage({ topic: undefined as unknown as string }),
            }

            await step(input)

            expect(mockIngestionLagGauge.labels).not.toHaveBeenCalled()
            expect(mockSetFn).not.toHaveBeenCalled()
        })

        it('should not record ingestion lag when inputMessage.partition is undefined', async () => {
            const step = createEmitEventStep(config)
            const input = {
                eventToEmit: mockRawEvent,
                inputHeaders: createHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
                inputMessage: createMessage({ partition: undefined as unknown as number }),
            }

            await step(input)

            expect(mockIngestionLagGauge.labels).not.toHaveBeenCalled()
            expect(mockSetFn).not.toHaveBeenCalled()
        })

        it('should use groupId from config in metric labels', async () => {
            const customConfig = { ...config, groupId: 'custom-consumer-group' }
            const step = createEmitEventStep(customConfig)
            const input = {
                eventToEmit: mockRawEvent,
                inputHeaders: createHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
                inputMessage: createMessage(),
            }

            await step(input)

            expect(mockIngestionLagGauge.labels).toHaveBeenCalledWith({
                topic: 'test-topic',
                partition: '5',
                groupId: 'custom-consumer-group',
            })
        })

        it('should handle partition 0 correctly', async () => {
            const step = createEmitEventStep(config)
            const input = {
                eventToEmit: mockRawEvent,
                inputHeaders: createHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
                inputMessage: createMessage({ partition: 0 }),
            }

            await step(input)

            expect(mockIngestionLagGauge.labels).toHaveBeenCalledWith({
                topic: 'test-topic',
                partition: '0',
                groupId: 'test-group-id',
            })
        })

        describe('histogram', () => {
            it('should observe lag in histogram with correct labels', async () => {
                const captureTime = new Date(FAKE_NOW_MS - 5432)
                const step = createEmitEventStep(config)
                const input = {
                    eventToEmit: mockRawEvent,
                    inputHeaders: createHeaders({ now: captureTime }),
                    inputMessage: createMessage(),
                }

                await step(input)

                expect(mockIngestionLagHistogram.labels).toHaveBeenCalledWith({
                    groupId: 'test-group-id',
                    partition: '5',
                })
                expect(mockObserveFn).toHaveBeenCalledTimes(1)
                expect(mockObserveFn).toHaveBeenCalledWith(5432)
            })

            it('should use custom groupId in histogram labels', async () => {
                const customConfig = { ...config, groupId: 'custom-consumer-group' }
                const step = createEmitEventStep(customConfig)
                const input = {
                    eventToEmit: mockRawEvent,
                    inputHeaders: createHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
                    inputMessage: createMessage({ partition: 3 }),
                }

                await step(input)

                expect(mockIngestionLagHistogram.labels).toHaveBeenCalledWith({
                    groupId: 'custom-consumer-group',
                    partition: '3',
                })
                expect(mockObserveFn).toHaveBeenCalledWith(1000)
            })

            it('should not observe histogram when inputHeaders.now is missing', async () => {
                const step = createEmitEventStep(config)
                const input = {
                    eventToEmit: mockRawEvent,
                    inputHeaders: createHeaders(),
                    inputMessage: createMessage(),
                }

                await step(input)

                expect(mockIngestionLagHistogram.labels).not.toHaveBeenCalled()
                expect(mockObserveFn).not.toHaveBeenCalled()
            })

            it('should not observe histogram when inputMessage.partition is undefined', async () => {
                const step = createEmitEventStep(config)
                const input = {
                    eventToEmit: mockRawEvent,
                    inputHeaders: createHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
                    inputMessage: createMessage({ partition: undefined as unknown as number }),
                }

                await step(input)

                expect(mockIngestionLagHistogram.labels).not.toHaveBeenCalled()
                expect(mockObserveFn).not.toHaveBeenCalled()
            })

            it('should handle partition 0 correctly in histogram', async () => {
                const step = createEmitEventStep(config)
                const input = {
                    eventToEmit: mockRawEvent,
                    inputHeaders: createHeaders({ now: new Date(FAKE_NOW_MS - 2500) }),
                    inputMessage: createMessage({ partition: 0 }),
                }

                await step(input)

                expect(mockIngestionLagHistogram.labels).toHaveBeenCalledWith({
                    groupId: 'test-group-id',
                    partition: '0',
                })
                expect(mockObserveFn).toHaveBeenCalledWith(2500)
            })
        })
    })
})
