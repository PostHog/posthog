import { KafkaProducerWrapper } from '../../kafka/producer'
import { ProjectId, RawKafkaEvent, TimestampFormat } from '../../types'
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

const mockCaptureIngestionWarning = jest.mocked(captureIngestionWarning)
const mockEventProcessedAndIngestedCounter = jest.mocked(eventProcessedAndIngestedCounter)

describe('emit-event-step', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let config: EmitEventStepConfig
    let mockRawEvent: RawKafkaEvent

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
            disconnect: jest.fn().mockResolvedValue(undefined),
        } as any

        config = {
            kafkaProducer: mockKafkaProducer,
            clickhouseJsonEventsTopic: 'clickhouse_events_json',
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
        }
    })

    describe('createEmitEventStep', () => {
        it('should emit event successfully when eventToEmit is present', async () => {
            const step = createEmitEventStep(config)
            const input = { eventToEmit: mockRawEvent }

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

        it('should return OK result with no side effects when eventToEmit is undefined', async () => {
            const step = createEmitEventStep(config)
            const input = { eventToEmit: undefined }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toBeUndefined()
            }
            expect(result.sideEffects).toHaveLength(0)
            expect(mockKafkaProducer.produce).not.toHaveBeenCalled()
            expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
        })

        it('should return OK result with no side effects when eventToEmit is not present', async () => {
            const step = createEmitEventStep(config)
            const input = {} as any

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toBeUndefined()
            }
            expect(result.sideEffects).toHaveLength(0)
            expect(mockKafkaProducer.produce).not.toHaveBeenCalled()
            expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
        })

        it('should handle MessageSizeTooLarge error and capture ingestion warning', async () => {
            const messageSizeTooLargeError = new MessageSizeTooLarge('Message too large', new Error('Kafka error'))
            mockKafkaProducer.produce.mockRejectedValue(messageSizeTooLargeError)

            const step = createEmitEventStep(config)
            const input = { eventToEmit: mockRawEvent }

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
            const input = { eventToEmit: mockRawEvent }

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
            const input = { eventToEmit: mockRawEvent }

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
            const input = { eventToEmit: mockRawEvent }

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
            const input = { eventToEmit: eventWithDifferentUuid }

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
                customProperty: string
                lastStep: string
            }

            const step = createEmitEventStep<CustomInput>(config)
            const input: CustomInput = {
                eventToEmit: mockRawEvent,
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
                eventToEmit?: RawKafkaEvent
                error?: string
            }

            const step = createEmitEventStep<EventPipelineResult>(config)
            const input: EventPipelineResult = {
                lastStep: 'createEventStep',
                eventToEmit: mockRawEvent,
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

        it('should handle heatmap results (no eventToEmit) gracefully', async () => {
            interface EventPipelineResult {
                lastStep: string
                eventToEmit?: RawKafkaEvent
                error?: string
            }

            const step = createEmitEventStep<EventPipelineResult>(config)
            const heatmapInput: EventPipelineResult = {
                lastStep: 'prepareEventStep',
                eventToEmit: undefined,
            }

            const result = await step(heatmapInput)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toBeUndefined()
            }
            expect(result.sideEffects).toHaveLength(0)
            expect(mockKafkaProducer.produce).not.toHaveBeenCalled()
        })

        describe('metrics tracking', () => {
            it('should increment eventProcessedAndIngestedCounter when event is successfully emitted', async () => {
                const step = createEmitEventStep(config)
                const input = { eventToEmit: mockRawEvent }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                expect(result.sideEffects).toHaveLength(1)

                // Execute the side effect to trigger metric increment
                await result.sideEffects[0]

                expect(mockEventProcessedAndIngestedCounter.inc).toHaveBeenCalledTimes(1)
                expect(mockKafkaProducer.produce).toHaveBeenCalledTimes(1)
            })

            it('should not increment metric when no event to emit', async () => {
                const step = createEmitEventStep(config)
                const input = { eventToEmit: undefined }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                expect(result.sideEffects).toHaveLength(0)
                expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
                expect(mockKafkaProducer.produce).not.toHaveBeenCalled()
            })

            it('should not increment metric when Kafka produce fails', async () => {
                const kafkaError = new Error('Kafka connection failed')
                mockKafkaProducer.produce.mockRejectedValue(kafkaError)

                const step = createEmitEventStep(config)
                const input = { eventToEmit: mockRawEvent }

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
                const input1 = { eventToEmit: mockRawEvent }
                const input2 = { eventToEmit: { ...mockRawEvent, uuid: 'different-uuid' } }

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
            const input = { eventToEmit: aiEvent }

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
})
