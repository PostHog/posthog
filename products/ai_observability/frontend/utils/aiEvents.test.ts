import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hasRecentAIEvents } from './aiEvents'

describe('aiEventsUtils', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    describe('hasRecentAIEvents', () => {
        it('returns true when a valid non-stale EventDefinition exists', async () => {
            const recentDate = dayjs().subtract(1, 'day').toISOString()

            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [
                            {
                                id: '1',
                                name: '$ai_generation',
                                last_seen_at: recentDate,
                            },
                        ],
                        count: 1,
                    },
                },
            })

            const queryApiSpy = jest.spyOn(api, 'query')

            const result = await hasRecentAIEvents()

            expect(result).toBe(true)
            expect(queryApiSpy).not.toHaveBeenCalled()
        })

        it('returns true for $ai_trace event type', async () => {
            const recentDate = dayjs().subtract(1, 'day').toISOString()

            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [
                            {
                                id: '1',
                                name: '$ai_trace',
                                last_seen_at: recentDate,
                            },
                        ],
                        count: 1,
                    },
                },
            })

            const result = await hasRecentAIEvents()

            expect(result).toBe(true)
        })

        it('falls back to ClickHouse when EventDefinition is stale', async () => {
            const staleDate = dayjs().subtract(120, 'day').toISOString()

            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [
                            {
                                id: '1',
                                name: '$ai_generation',
                                last_seen_at: staleDate,
                            },
                        ],
                        count: 1,
                    },
                },
            })

            const queryApiSpy = jest.spyOn(api, 'query').mockResolvedValue({
                results: [[1]],
            } as any)

            const result = await hasRecentAIEvents()

            expect(result).toBe(true)
            expect(queryApiSpy).toHaveBeenCalled()
        })

        it('falls back to ClickHouse when no EventDefinition exists', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [],
                        count: 0,
                    },
                },
            })

            const queryApiSpy = jest.spyOn(api, 'query').mockResolvedValue({
                results: [[1]],
            } as any)

            const result = await hasRecentAIEvents()

            expect(result).toBe(true)
            // Pointing this back at the shared `events` table costs a full scan of the team's
            // 12-hour window, because this branch only runs for teams with nothing to match.
            expect(queryApiSpy.mock.calls[0][0]).toMatchObject({
                query: expect.stringContaining('FROM posthog.ai_events'),
            })
        })

        it('returns undefined instead of throwing when the detection query fails', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [],
                        count: 0,
                    },
                },
            })

            jest.spyOn(api, 'query').mockRejectedValue(new Error('ClickHouse error while executing query.'))
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})

            try {
                // Callers poll this, so a rejection would toast and report on every tick.
                await expect(hasRecentAIEvents()).resolves.toBeUndefined()
            } finally {
                warnSpy.mockRestore()
            }
        })

        it('returns false when neither Postgres nor ClickHouse has AI events', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [],
                        count: 0,
                    },
                },
            })

            jest.spyOn(api, 'query').mockResolvedValue({
                results: [],
            } as any)

            const result = await hasRecentAIEvents()

            expect(result).toBe(false)
        })

        it('ignores non-AI event definitions in search results', async () => {
            const recentDate = dayjs().subtract(1, 'day').toISOString()

            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [
                            {
                                id: '1',
                                name: '$ai_something_else',
                                last_seen_at: recentDate,
                            },
                        ],
                        count: 1,
                    },
                },
            })

            const queryApiSpy = jest.spyOn(api, 'query').mockResolvedValue({
                results: [],
            } as any)

            const result = await hasRecentAIEvents()

            expect(result).toBe(false)
            expect(queryApiSpy).toHaveBeenCalled()
        })

        it('falls back to ClickHouse when the EventDefinition list resolves to null', async () => {
            jest.spyOn(api.eventDefinitions, 'list').mockResolvedValueOnce(null as any)

            const queryApiSpy = jest.spyOn(api, 'query').mockResolvedValue({
                results: [[1]],
            } as any)

            const result = await hasRecentAIEvents()

            expect(result).toBe(true)
            expect(queryApiSpy).toHaveBeenCalled()
        })

        it('handles null results from ClickHouse gracefully', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [],
                        count: 0,
                    },
                },
            })

            jest.spyOn(api, 'query').mockResolvedValue({
                results: null,
            } as any)

            const result = await hasRecentAIEvents()

            expect(result).toBe(false)
        })

        it('handles undefined results from ClickHouse gracefully', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/': {
                        results: [],
                        count: 0,
                    },
                },
            })

            jest.spyOn(api, 'query').mockResolvedValue({} as any)

            const result = await hasRecentAIEvents()

            expect(result).toBe(false)
        })
    })
})
