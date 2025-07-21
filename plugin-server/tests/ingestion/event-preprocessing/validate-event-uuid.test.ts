import { validateEventUuid } from '../../../src/ingestion/event-preprocessing/validate-event-uuid'
import { Hub, IncomingEventWithTeam } from '../../../src/types'
import { captureIngestionWarning } from '../../../src/worker/ingestion/utils'
import { getMetricValues, resetMetrics } from '../../helpers/metrics'

// Mock the captureIngestionWarning function
jest.mock('../../../src/worker/ingestion/utils')
const mockCaptureIngestionWarning = captureIngestionWarning as jest.MockedFunction<typeof captureIngestionWarning>

describe('validateEventUuid', () => {
    let mockHub: Pick<Hub, 'db'>
    let mockEventWithTeam: IncomingEventWithTeam

    beforeEach(() => {
        resetMetrics()
        mockHub = {
            db: {
                kafkaProducer: {} as any,
            } as any,
        }

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
        }

        jest.clearAllMocks()
    })

    it('should return eventWithTeam when UUID is valid', async () => {
        const result = await validateEventUuid(mockEventWithTeam, mockHub)

        expect(result).toBe(mockEventWithTeam)
        expect(mockCaptureIngestionWarning).not.toHaveBeenCalled()
    })

    it('should return null when UUID is invalid', async () => {
        mockEventWithTeam.event.uuid = 'invalid-uuid'

        const result = await validateEventUuid(mockEventWithTeam, mockHub)

        expect(result).toBeNull()
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: '"invalid-uuid"' }
        )
    })

    it('should return null when UUID is null', async () => {
        mockEventWithTeam.event.uuid = null as any

        const result = await validateEventUuid(mockEventWithTeam, mockHub)

        expect(result).toBeNull()
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: 'null' }
        )
    })

    it('should return null when UUID is undefined', async () => {
        mockEventWithTeam.event.uuid = undefined as any

        const result = await validateEventUuid(mockEventWithTeam, mockHub)

        expect(result).toBeNull()
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: undefined }
        )
    })

    it('should return null when UUID is empty string', async () => {
        mockEventWithTeam.event.uuid = ''

        const result = await validateEventUuid(mockEventWithTeam, mockHub)

        expect(result).toBeNull()
        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            1,
            'skipping_event_invalid_uuid',
            { eventUuid: '""' }
        )
    })

    it('should increment metrics when UUID is invalid', async () => {
        mockEventWithTeam.event.uuid = 'invalid-uuid'

        await validateEventUuid(mockEventWithTeam, mockHub)

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

        await validateEventUuid(mockEventWithTeam, mockHub)

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

        await validateEventUuid(mockEventWithTeam, mockHub)

        expect(mockCaptureIngestionWarning).toHaveBeenCalledWith(
            mockHub.db.kafkaProducer,
            999,
            'skipping_event_invalid_uuid',
            { eventUuid: '"invalid-uuid"' }
        )
    })

    it('should preserve event data when UUID is valid', async () => {
        const result = await validateEventUuid(mockEventWithTeam, mockHub)

        expect(result?.event.token).toBe('test-token-123')
        expect(result?.event.distinct_id).toBe('test-user-456')
        expect(result?.event.event).toBe('test-event')
        expect(result?.event.properties).toEqual({ testProp: 'testValue' })
        expect(result?.event.ip).toBe('127.0.0.1')
        expect(result?.event.site_url).toBe('https://example.com')
        expect(result?.event.now).toBe(mockEventWithTeam.event.now)
        expect(result?.event.uuid).toBe('123e4567-e89b-12d3-a456-426614174000')
        expect(result?.team.id).toBe(1)
        expect(result?.team.name).toBe('Test Team')
        expect(result?.team.person_processing_opt_out).toBe(false)
        expect(result?.message).toBe(mockEventWithTeam.message)
    })
})
