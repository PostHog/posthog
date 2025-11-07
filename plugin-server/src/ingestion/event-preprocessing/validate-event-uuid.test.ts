import { PipelineEvent } from '../../types'
import { PipelineResultType, drop, ok } from '../pipelines/results'
import { createValidateEventUuidStep } from './validate-event-uuid'

describe('createValidateEventUuidStep', () => {
    let mockEvent: PipelineEvent
    let step: ReturnType<typeof createValidateEventUuidStep>

    beforeEach(() => {
        mockEvent = {
            token: 'test-token-123',
            distinct_id: 'test-user-456',
            event: 'test-event',
            properties: { testProp: 'testValue' },
            ip: '127.0.0.1',
            site_url: 'https://example.com',
            now: '2020-02-23T02:15:00Z',
            uuid: '123e4567-e89b-12d3-a456-426614174000',
        }

        step = createValidateEventUuidStep()
        jest.clearAllMocks()
    })

    it('should return success when UUID is valid', async () => {
        const input = { event: mockEvent }
        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should return drop when UUID is invalid', async () => {
        mockEvent.uuid = 'invalid-uuid'
        const input = { event: mockEvent }

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
        mockEvent.uuid = null as any
        const input = { event: mockEvent }

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
        mockEvent.uuid = undefined as any
        const input = { event: mockEvent }

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
        mockEvent.uuid = ''
        const input = { event: mockEvent }

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
        mockEvent.uuid = 'invalid-uuid'
        const input = { event: mockEvent }

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
        const input = { event: mockEvent }
        const result = await step(input)

        expect(result).toEqual(ok(input))

        if (result.type === PipelineResultType.OK) {
            expect(result.value.event.token).toBe('test-token-123')
            expect(result.value.event.distinct_id).toBe('test-user-456')
            expect(result.value.event.event).toBe('test-event')
            expect(result.value.event.properties).toEqual({ testProp: 'testValue' })
            expect(result.value.event.ip).toBe('127.0.0.1')
            expect(result.value.event.site_url).toBe('https://example.com')
            expect(result.value.event.now).toBe(mockEvent.now)
            expect(result.value.event.uuid).toBe('123e4567-e89b-12d3-a456-426614174000')
        }
    })
})
