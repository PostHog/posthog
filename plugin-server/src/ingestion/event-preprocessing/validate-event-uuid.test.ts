import { IncomingEventWithTeam } from '../../types'
import { PipelineResultType, drop, ok } from '../pipelines/results'
import { createValidateEventUuidStep } from './validate-event-uuid'

describe('createValidateEventUuidStep', () => {
    let mockEventWithTeam: IncomingEventWithTeam
    let step: ReturnType<typeof createValidateEventUuidStep>

    beforeEach(() => {
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
            headers: {
                force_disable_person_processing: false,
            },
        }

        step = createValidateEventUuidStep()
        jest.clearAllMocks()
    })

    it('should return success when UUID is valid', async () => {
        const input = { eventWithTeam: mockEventWithTeam }
        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should return drop when UUID is invalid', async () => {
        mockEventWithTeam.event.uuid = 'invalid-uuid'
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'invalid_uuid',
                [],
                [
                    {
                        type: 'skipping_event_invalid_uuid',
                        details: { eventUuid: '"invalid-uuid"' },
                    },
                ]
            )
        )
    })

    it('should return drop when UUID is null', async () => {
        mockEventWithTeam.event.uuid = null as any
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'empty_uuid',
                [],
                [
                    {
                        type: 'skipping_event_invalid_uuid',
                        details: { eventUuid: 'null' },
                    },
                ]
            )
        )
    })

    it('should return drop when UUID is undefined', async () => {
        mockEventWithTeam.event.uuid = undefined as any
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'empty_uuid',
                [],
                [
                    {
                        type: 'skipping_event_invalid_uuid',
                        details: { eventUuid: undefined },
                    },
                ]
            )
        )
    })

    it('should return drop when UUID is empty string', async () => {
        mockEventWithTeam.event.uuid = ''
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'empty_uuid',
                [],
                [
                    {
                        type: 'skipping_event_invalid_uuid',
                        details: { eventUuid: '""' },
                    },
                ]
            )
        )
    })

    it('should include warning in result when UUID is invalid', async () => {
        mockEventWithTeam.team.id = 999
        mockEventWithTeam.event.uuid = 'invalid-uuid'
        const input = { eventWithTeam: mockEventWithTeam }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'invalid_uuid',
                [],
                [
                    {
                        type: 'skipping_event_invalid_uuid',
                        details: { eventUuid: '"invalid-uuid"' },
                    },
                ]
            )
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
