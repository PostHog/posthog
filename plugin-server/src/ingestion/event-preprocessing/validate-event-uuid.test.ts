import { getMetricValues, resetMetrics } from '../../../tests/helpers/metrics'
import { Hub, IncomingEventWithTeam } from '../../types'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { PipelineResultType, drop, ok } from '../pipelines/results'
import { createValidateEventUuidStep } from './validate-event-uuid'

// Mock the captureIngestionWarning function
jest.mock('../../../src/worker/ingestion/utils')
const mockCaptureIngestionWarning = captureIngestionWarning as jest.MockedFunction<typeof captureIngestionWarning>

describe('createValidateEventUuidStep', () => {
    let mockHub: Hub
    let mockEventWithTeam: IncomingEventWithTeam
    let step: ReturnType<typeof createValidateEventUuidStep>

    beforeEach(() => {
        resetMetrics()
        mockHub = {
            db: {
                kafkaProducer: {} as any,
            } as any,
        } as Hub

        mockEventWithTeam = {
            event: {
                token: 'test-token-123',
                distinct_id: 'test-user-456',
                event: 'test-event',
                properties: { testProp: 'testValue' },
                ip: '127.0.0.1',
                site_url: 'https://example.com',
                now: '2020-02-23T02:15:00Z',
                uuid: '123e4567-e89b-12d3-a456-426614174000',
            },
            team: {
                id: 1,
                name: 'Test Team',
                person_processing_opt_out: false,
            } as any,
            message: {} as any,
            headers: {},
        }

        step = createValidateEventUuidStep(mockHub)
        jest.clearAllMocks()
    })

    it('should return success when UUID is valid', async () => {
        const input = { eventWithTeam: mockEventWithTeam }
        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(mockCaptureIngestionWarning).not.toHaveBeenCalled()
    })

    it('should return drop when UUID is invalid', async () => {
        mockEventWithTeam.event.uuid = 'invalid-uuid'
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(drop('Event has invalid UUID'))
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: '"invalid-uuid"' }
        )
    })

    it('should return drop when UUID is null', async () => {
        mockEventWithTeam.event.uuid = null as any
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(drop('Event has invalid UUID'))
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: 'null' }
        )
    })

    it('should return drop when UUID is undefined', async () => {
        mockEventWithTeam.event.uuid = undefined as any
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(drop('Event has invalid UUID'))
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: undefined }
        )
    })

    it('should return drop when UUID is empty string', async () => {
        mockEventWithTeam.event.uuid = ''
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(drop('Event has invalid UUID'))
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: '""' }
        )
    })

    it('should increment metrics when UUID is invalid', async () => {
        mockEventWithTeam.event.uuid = 'invalid-uuid'
        const input = { eventWithTeam: mockEventWithTeam }

        await step(input)

        const metrics = await getMetricValues('ingestion_event_dropped_total')
        expect(metrics).toEqual([
            {
                labels: {
                    drop_cause: 'invalid_uuid',
                    event_type: 'analytics',
                },
                value: 1,
            },
        ])
    })

    it('should increment metrics with empty_uuid when UUID is null', async () => {
        mockEventWithTeam.event.uuid = null as any
        const input = { eventWithTeam: mockEventWithTeam }

        await step(input)

        const metrics = await getMetricValues('ingestion_event_dropped_total')
        expect(metrics).toEqual([
            {
                labels: {
                    drop_cause: 'empty_uuid',
                    event_type: 'analytics',
                },
                value: 1,
            },
        ])
    })

    it('should handle different team IDs', async () => {
        mockEventWithTeam.team.id = 999
        mockEventWithTeam.event.uuid = 'invalid-uuid'
        const input = { eventWithTeam: mockEventWithTeam }

        await step(input)

        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            999,
            'skipping_event_invalid_uuid',
            { eventUuid: '"invalid-uuid"' }
        )
    })

    it('should preserve event data when UUID is valid', async () => {
        const input = { eventWithTeam: mockEventWithTeam }
        const result = await step(input)

        expect(result).toEqual(ok(input))

        if (result.type === PipelineResultType.OK) {
            expect(result.value.eventWithTeam.event.token).toBe('test-token-123')
            expect(result.value.eventWithTeam.event.distinct_id).toBe('test-user-456')
            expect(result.value.eventWithTeam.event.event).toBe('test-event')
            expect(result.value.eventWithTeam.event.properties).toEqual({ testProp: 'testValue' })
            expect(result.value.eventWithTeam.event.ip).toBe('127.0.0.1')
            expect(result.value.eventWithTeam.event.site_url).toBe('https://example.com')
            expect(result.value.eventWithTeam.event.now).toBe(mockEventWithTeam.event.now)
            expect(result.value.eventWithTeam.event.uuid).toBe('123e4567-e89b-12d3-a456-426614174000')
            expect(result.value.eventWithTeam.team.id).toBe(1)
            expect(result.value.eventWithTeam.team.name).toBe('Test Team')
            expect(result.value.eventWithTeam.team.person_processing_opt_out).toBe(false)
            expect(result.value.eventWithTeam.message).toBe(mockEventWithTeam.message)
        }
    })
})
