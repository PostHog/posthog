import { drop, ok } from '../pipelines/results'
import { createValidateEventPropertiesStep } from './validate-event-properties'

// Mock the dependencies
jest.mock('../../main/ingestion-queues/metrics', () => ({
    eventDroppedCounter: {
        labels: jest.fn().mockReturnThis(),
        inc: jest.fn(),
    },
}))

describe('createValidateEventPropertiesStep', () => {
    const step = createValidateEventPropertiesStep()

    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('group identify validation', () => {
        it('should drop $groupidentify events with group_key longer than 400 characters', async () => {
            const longGroupKey = 'a'.repeat(401)
            const input = {
                event: {
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    uuid: '123e4567-e89b-12d3-a456-426614174000',
                    ip: '127.0.0.1',
                    site_url: 'https://example.com',
                    now: '2021-01-01T00:00:00Z',
                    properties: {
                        $group_key: longGroupKey,
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual(
                drop(
                    'group_key_too_long',
                    [],
                    [
                        {
                            type: 'group_key_too_long',
                            details: {
                                eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                                event: '$groupidentify',
                                distinctId: 'user123',
                                groupKey: longGroupKey,
                                groupKeyLength: 401,
                                maxLength: 400,
                            },
                        },
                    ]
                )
            )
        })

        it('should allow $groupidentify events with group_key shorter than 400 characters', async () => {
            const shortGroupKey = 'a'.repeat(399)
            const input = {
                event: {
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    uuid: '123e4567-e89b-12d3-a456-426614174000',
                    ip: '127.0.0.1',
                    site_url: 'https://example.com',
                    now: '2021-01-01T00:00:00Z',
                    properties: {
                        $group_key: shortGroupKey,
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should allow $groupidentify events with group_key exactly 400 characters', async () => {
            const exactGroupKey = 'a'.repeat(400)
            const input = {
                event: {
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    uuid: '123e4567-e89b-12d3-a456-426614174000',
                    ip: '127.0.0.1',
                    site_url: 'https://example.com',
                    now: '2021-01-01T00:00:00Z',
                    properties: {
                        $group_key: exactGroupKey,
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should allow $groupidentify events without group_key', async () => {
            const input = {
                event: {
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    uuid: '123e4567-e89b-12d3-a456-426614174000',
                    ip: '127.0.0.1',
                    site_url: 'https://example.com',
                    now: '2021-01-01T00:00:00Z',
                    properties: {},
                },
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })

    describe('other event types', () => {
        it('should allow non-groupidentify events', async () => {
            const input = {
                event: {
                    event: '$pageview',
                    distinct_id: 'user123',
                    team_id: 1,
                    uuid: '123e4567-e89b-12d3-a456-426614174000',
                    ip: '127.0.0.1',
                    site_url: 'https://example.com',
                    now: '2021-01-01T00:00:00Z',
                },
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should allow regular events', async () => {
            const input = {
                event: {
                    event: 'button_clicked',
                    distinct_id: 'user123',
                    team_id: 1,
                    uuid: '123e4567-e89b-12d3-a456-426614174000',
                    ip: '127.0.0.1',
                    site_url: 'https://example.com',
                    now: '2021-01-01T00:00:00Z',
                },
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })
})
