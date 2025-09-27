import { Hub, IncomingEventWithTeam } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { createValidateEventPropertiesStep } from './validate-event-properties'

// Mock the dependencies
jest.mock('../../main/ingestion-queues/metrics', () => ({
    eventDroppedCounter: {
        labels: jest.fn().mockReturnThis(),
        inc: jest.fn(),
    },
}))

jest.mock('../../worker/ingestion/utils', () => ({
    captureIngestionWarning: jest.fn(),
}))

describe('createValidateEventPropertiesStep', () => {
    const mockHub = {
        db: {
            kafkaProducer: {} as any,
        },
    } as Hub

    const step = createValidateEventPropertiesStep(mockHub)

    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('group identify validation', () => {
        it('should drop $groupidentify events with group_key longer than 400 characters', async () => {
            const longGroupKey = 'a'.repeat(401)
            const input = {
                eventWithTeam: {
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
                    team: {
                        id: 1,
                        name: 'Test Team',
                    },
                    message: {} as any,
                    headers: {} as any,
                } as unknown as IncomingEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.DROP,
                reason: 'Group key too long',
            })
        })

        it('should allow $groupidentify events with group_key shorter than 400 characters', async () => {
            const shortGroupKey = 'a'.repeat(399)
            const input = {
                eventWithTeam: {
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
                    team: {
                        id: 1,
                        name: 'Test Team',
                    },
                    message: {} as any,
                    headers: {} as any,
                } as unknown as IncomingEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })

        it('should allow $groupidentify events with group_key exactly 400 characters', async () => {
            const exactGroupKey = 'a'.repeat(400)
            const input = {
                eventWithTeam: {
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
                    team: {
                        id: 1,
                        name: 'Test Team',
                    },
                    message: {} as any,
                    headers: {} as any,
                } as unknown as IncomingEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })

        it('should allow $groupidentify events without group_key', async () => {
            const input = {
                eventWithTeam: {
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
                    team: {
                        id: 1,
                        name: 'Test Team',
                    },
                    message: {} as any,
                    headers: {} as any,
                } as unknown as IncomingEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })
    })

    describe('other event types', () => {
        it('should allow non-groupidentify events', async () => {
            const input = {
                eventWithTeam: {
                    event: {
                        event: '$pageview',
                        distinct_id: 'user123',
                        team_id: 1,
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                    },
                    team: {
                        id: 1,
                        name: 'Test Team',
                    },
                    message: {} as any,
                    headers: {} as any,
                } as unknown as IncomingEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })

        it('should allow regular events', async () => {
            const input = {
                eventWithTeam: {
                    event: {
                        event: 'button_clicked',
                        distinct_id: 'user123',
                        team_id: 1,
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                    },
                    team: {
                        id: 1,
                        name: 'Test Team',
                    },
                    message: {} as any,
                    headers: {} as any,
                } as unknown as IncomingEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })
    })
})
