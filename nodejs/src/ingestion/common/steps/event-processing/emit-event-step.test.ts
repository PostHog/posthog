import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { IngestionWarningsOutput } from '~/common/outputs'
import { EVENTS_OUTPUT, EventOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { eventProcessedAndIngestedCounter } from '~/ingestion/common/metrics'
import { isOkResult } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { EventHeaders, ISOTimestamp, ProcessedEvent, ProjectId } from '~/types'

import {
    EmitEventStepConfig,
    EmitEventStepInput,
    createEmitEventStep,
    productTrackHeader,
    serializeEvent,
} from './emit-event-step'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

// Mock the metrics module
jest.mock('~/ingestion/common/metrics', () => ({
    eventProcessedAndIngestedCounter: {
        inc: jest.fn(),
    },
}))

const mockEmitIngestionWarning = jest.mocked(emitIngestionWarning)
const mockEventProcessedAndIngestedCounter = jest.mocked(eventProcessedAndIngestedCounter)

describe('emit-event-step', () => {
    let mockOutputs: jest.Mocked<IngestionOutputs<EventOutput | IngestionWarningsOutput>>
    let config: EmitEventStepConfig<EventOutput>
    let mockProcessedEvent: ProcessedEvent
    let mockHeaders: EventHeaders
    let mockMessage: Message

    beforeEach(() => {
        mockHeaders = createTestEventHeaders()
        mockMessage = createTestMessage()
        jest.clearAllMocks()

        mockOutputs = createMockIngestionOutputs<EventOutput | IngestionWarningsOutput>()

        config = {
            outputs: mockOutputs,
        }

        mockProcessedEvent = {
            uuid: 'test-uuid',
            event: 'test-event',
            properties: { test: 'property' },
            timestamp: '2023-01-01T00:00:00.000Z' as ISOTimestamp,
            team_id: 1,
            project_id: 1 as ProjectId,
            distinct_id: 'test-distinct-id',
            elements_chain: '',
            created_at: null,
            captured_at: null,
            person_id: 'person-uuid',
            person_properties: {},
            person_created_at: DateTime.fromISO('2023-01-01T00:00:00.000Z'),
            person_mode: 'full',
        }
    })

    function createInput(event: ProcessedEvent = mockProcessedEvent): EmitEventStepInput<EventOutput> {
        return {
            eventsToEmit: [{ event, output: EVENTS_OUTPUT }],
            teamId: event.team_id,
            headers: mockHeaders,
            message: mockMessage,
        }
    }

    describe('createEmitEventStep', () => {
        it('should emit event successfully when eventsToEmit is present', async () => {
            jest.useFakeTimers()
            try {
                const step = createEmitEventStep(config)
                const input = createInput()

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(result.value.ingested).toHaveLength(1)
                    expect(result.value.ingested).toEqual(result.sideEffects)
                }
                expect(result.sideEffects).toHaveLength(1)
                expect(mockOutputs.produce).toHaveBeenCalledWith(EVENTS_OUTPUT, {
                    key: 'test-uuid',
                    value: Buffer.from(JSON.stringify(serializeEvent(mockProcessedEvent))),
                    headers: { productTrack: 'general' },
                    teamId: mockProcessedEvent.team_id,
                })

                // The ingested promise resolves with the event info once acked
                await expect(result.sideEffects[0]).resolves.toEqual({
                    capturedAt: mockHeaders.now,
                    topic: mockMessage.topic,
                    partition: mockMessage.partition,
                })
                expect(mockEventProcessedAndIngestedCounter.inc).toHaveBeenCalledTimes(1)
            } finally {
                jest.useRealTimers()
            }
        })

        it('should handle MessageSizeTooLarge error and capture ingestion warning', async () => {
            const messageSizeTooLargeError = new MessageSizeTooLarge('Message too large', new Error('Kafka error'))
            mockOutputs.produce.mockRejectedValue(messageSizeTooLargeError)

            const step = createEmitEventStep(config)
            const input = createInput()

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            expect(result.sideEffects).toHaveLength(1)

            // The event was not ingested, so the promise resolves with null
            await expect(result.sideEffects[0]).resolves.toBeNull()

            expect(mockEmitIngestionWarning).toHaveBeenCalledWith(mockOutputs, 1, {
                type: 'message_size_too_large',
                details: {
                    eventUuid: 'test-uuid',
                    distinctId: 'test-distinct-id',
                },
                category: 'size',
                severity: 'error',
                pipelineStep: 'emit-event',
            })
            // Metric should not be incremented when there's an error
            expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
        })

        it('should re-throw non-MessageSizeTooLarge errors', async () => {
            const genericError = new Error('Generic Kafka error')
            mockOutputs.produce.mockRejectedValue(genericError)

            const step = createEmitEventStep(config)
            const input = createInput()

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            expect(result.sideEffects).toHaveLength(1)

            // Execute the side effect to test error handling
            await expect(result.sideEffects[0]).rejects.toThrow('Generic Kafka error')
            expect(mockEmitIngestionWarning).not.toHaveBeenCalled()
            // Metric should not be incremented when there's an error
            expect(mockEventProcessedAndIngestedCounter.inc).not.toHaveBeenCalled()
        })

        it('should serialize event correctly for Kafka', async () => {
            jest.useFakeTimers()
            try {
                const step = createEmitEventStep(config)
                const input = createInput()

                await step(input)

                expect(mockOutputs.produce).toHaveBeenCalledWith(EVENTS_OUTPUT, {
                    key: 'test-uuid',
                    value: Buffer.from(JSON.stringify(serializeEvent(mockProcessedEvent))),
                    headers: { productTrack: 'general' },
                    teamId: mockProcessedEvent.team_id,
                })
            } finally {
                jest.useRealTimers()
            }
        })

        it('should handle events with different UUIDs correctly', async () => {
            const step = createEmitEventStep(config)
            const eventWithDifferentUuid = { ...mockProcessedEvent, uuid: 'different-uuid' }
            const input = createInput(eventWithDifferentUuid)

            await step(input)

            expect(mockOutputs.produce).toHaveBeenCalledWith(
                EVENTS_OUTPUT,
                expect.objectContaining({
                    key: 'different-uuid',
                })
            )
        })

        it('should handle multiple events in eventsToEmit', async () => {
            const step = createEmitEventStep(config)
            const event2 = { ...mockProcessedEvent, uuid: 'second-uuid' }
            const input: EmitEventStepInput<EventOutput> = {
                eventsToEmit: [
                    { event: mockProcessedEvent, output: EVENTS_OUTPUT },
                    { event: event2, output: EVENTS_OUTPUT },
                ],
                teamId: 1,
                headers: mockHeaders,
                message: mockMessage,
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            expect(result.sideEffects).toHaveLength(2)
            expect(mockOutputs.produce).toHaveBeenCalledTimes(2)
        })

        describe('metrics tracking', () => {
            it('should increment eventProcessedAndIngestedCounter when event is successfully emitted', async () => {
                const step = createEmitEventStep(config)
                const input = createInput()

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                expect(result.sideEffects).toHaveLength(1)

                // Execute the side effect to trigger metric increment
                await result.sideEffects[0]

                expect(mockEventProcessedAndIngestedCounter.inc).toHaveBeenCalledTimes(1)
                expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
            })

            it('should not increment metric when Kafka produce fails', async () => {
                const kafkaError = new Error('Kafka connection failed')
                mockOutputs.produce.mockRejectedValue(kafkaError)

                const step = createEmitEventStep(config)
                const input = createInput()

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

                // First emit
                const result1 = await step(createInput())
                await result1.sideEffects[0]

                // Second emit
                const result2 = await step(createInput({ ...mockProcessedEvent, uuid: 'different-uuid' }))
                await result2.sideEffects[0]

                // Metric should be incremented twice, once for each successful emit
                expect(mockEventProcessedAndIngestedCounter.inc).toHaveBeenCalledTimes(2)
                expect(mockOutputs.produce).toHaveBeenCalledTimes(2)
            })
        })

        it('should emit AI events with llma product track header', async () => {
            const aiEvent = { ...mockProcessedEvent, event: '$ai_generation' }
            const step = createEmitEventStep(config)
            const input = createInput(aiEvent)

            await step(input)

            expect(mockOutputs.produce).toHaveBeenCalledWith(
                EVENTS_OUTPUT,
                expect.objectContaining({
                    headers: { productTrack: 'llma' },
                })
            )
        })
    })

    describe('productTrackHeader', () => {
        it('should return "llma" for AI generation events', () => {
            const aiEvent = { ...mockProcessedEvent, event: '$ai_generation' }
            expect(productTrackHeader(aiEvent)).toBe('llma')
        })

        it('should return "llma" for AI completion events', () => {
            const aiEvent = { ...mockProcessedEvent, event: '$ai_completion' }
            expect(productTrackHeader(aiEvent)).toBe('llma')
        })

        it('should return "general" for non-AI events', () => {
            const regularEvent = { ...mockProcessedEvent, event: '$pageview' }
            expect(productTrackHeader(regularEvent)).toBe('general')
        })

        it('should return "general" for custom events', () => {
            const customEvent = { ...mockProcessedEvent, event: 'user_signed_up' }
            expect(productTrackHeader(customEvent)).toBe('general')
        })
    })
})
