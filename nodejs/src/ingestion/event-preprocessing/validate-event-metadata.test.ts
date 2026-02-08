import { EventHeaders } from '../../types'
import { drop, ok } from '../pipelines/results'
import { createValidateEventMetadataStep } from './validate-event-metadata'

describe('createValidateEventMetadataStep', () => {
    let mockHeaders: EventHeaders
    let step: ReturnType<typeof createValidateEventMetadataStep>

    beforeEach(() => {
        mockHeaders = {
            token: 'test-token-123',
            distinct_id: 'test-user-456',
            force_disable_person_processing: false,
            historical_migration: false,
        }

        step = createValidateEventMetadataStep()
        jest.clearAllMocks()
    })

    it('should return success when distinct_id is valid', async () => {
        const input = { headers: mockHeaders }
        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should return success when distinct_id is exactly 400 characters', async () => {
        mockHeaders.distinct_id = 'a'.repeat(400)
        const input = { headers: mockHeaders }

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should return success when distinct_id is undefined', async () => {
        mockHeaders.distinct_id = undefined
        const input = { headers: mockHeaders }

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should return drop when distinct_id is longer than 400 characters', async () => {
        const longDistinctId = 'a'.repeat(401)
        mockHeaders.distinct_id = longDistinctId
        const input = { headers: mockHeaders }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'distinct_id_too_long',
                [],
                [
                    {
                        type: 'skipping_event_invalid_distinct_id',
                        details: {
                            distinctId: 'a'.repeat(100),
                            distinctIdLength: 401,
                            maxLength: 400,
                        },
                    },
                ]
            )
        )
    })

    it('should return drop when distinct_id is much longer than 400 characters', async () => {
        const veryLongDistinctId = 'x'.repeat(1000)
        mockHeaders.distinct_id = veryLongDistinctId
        const input = { headers: mockHeaders }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'distinct_id_too_long',
                [],
                [
                    {
                        type: 'skipping_event_invalid_distinct_id',
                        details: {
                            distinctId: 'x'.repeat(100),
                            distinctIdLength: 1000,
                            maxLength: 400,
                        },
                    },
                ]
            )
        )
    })

    it('should truncate distinct_id to 100 characters in warning details', async () => {
        const longDistinctId = 'b'.repeat(500)
        mockHeaders.distinct_id = longDistinctId
        const input = { headers: mockHeaders }

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'distinct_id_too_long',
                [],
                [
                    {
                        type: 'skipping_event_invalid_distinct_id',
                        details: {
                            distinctId: 'b'.repeat(100),
                            distinctIdLength: 500,
                            maxLength: 400,
                        },
                    },
                ]
            )
        )
    })
})
