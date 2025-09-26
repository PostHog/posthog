import { PipelineResultType } from '../pipelines/results'
import { createDropExceptionEventsStep } from './drop-exception-events'

describe('createDropExceptionEventsStep', () => {
    const step = createDropExceptionEventsStep()

    describe('exception event handling', () => {
        it('should drop $exception events', async () => {
            const input = {
                event: {
                    event: {
                        event: '$exception',
                        distinct_id: 'user123',
                        team_id: 1,
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                    },
                    headers: {
                        token: 'token123',
                        distinct_id: 'user123',
                        timestamp: '2021-01-01T00:00:00Z',
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.DROP,
                reason: 'Exception events are processed separately in Rust',
            })
        })

        it('should allow non-exception events', async () => {
            const input = {
                event: {
                    event: {
                        event: '$pageview',
                        distinct_id: 'user123',
                        team_id: 1,
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                    },
                    headers: {
                        token: 'token123',
                        distinct_id: 'user123',
                        timestamp: '2021-01-01T00:00:00Z',
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })

        it('should allow regular events', async () => {
            const input = {
                event: {
                    event: {
                        event: 'button_clicked',
                        distinct_id: 'user123',
                        team_id: 1,
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                    },
                    headers: {
                        token: 'token123',
                        distinct_id: 'user123',
                        timestamp: '2021-01-01T00:00:00Z',
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })

        it('should allow identify events', async () => {
            const input = {
                event: {
                    event: {
                        event: '$identify',
                        distinct_id: 'user123',
                        team_id: 1,
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                    },
                    headers: {
                        token: 'token123',
                        distinct_id: 'user123',
                        timestamp: '2021-01-01T00:00:00Z',
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })

        it('should allow group identify events', async () => {
            const input = {
                event: {
                    event: {
                        event: '$groupidentify',
                        distinct_id: 'user123',
                        team_id: 1,
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                    },
                    headers: {
                        token: 'token123',
                        distinct_id: 'user123',
                        timestamp: '2021-01-01T00:00:00Z',
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })

        it('should allow heatmap events', async () => {
            const input = {
                event: {
                    event: {
                        event: '$$heatmap',
                        distinct_id: 'user123',
                        team_id: 1,
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        now: '2021-01-01T00:00:00Z',
                        uuid: '123e4567-e89b-12d3-a456-426614174000',
                    },
                    headers: {
                        token: 'token123',
                        distinct_id: 'user123',
                        timestamp: '2021-01-01T00:00:00Z',
                    },
                },
            }

            const result = await step(input)

            expect(result).toEqual({
                type: PipelineResultType.OK,
                value: input,
            })
        })
    })
})
