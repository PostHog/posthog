import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hasRecentAIEvents, pollRecentAIEvents } from './aiEvents'

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
            expect(queryApiSpy).toHaveBeenCalled()
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

    describe('pollRecentAIEvents', () => {
        it('dedupes concurrent calls, caches a positive result, and re-checks after a team switch', async () => {
            const listSpy = jest.spyOn(api.eventDefinitions, 'list').mockResolvedValue({
                results: [{ id: '1', name: '$ai_generation', last_seen_at: dayjs().subtract(1, 'day').toISOString() }],
                count: 1,
            } as any)

            const [first, second] = await Promise.all([pollRecentAIEvents(1), pollRecentAIEvents(1)])
            expect(first).toBe(true)
            expect(second).toBe(true)
            expect(listSpy).toHaveBeenCalledTimes(1)

            expect(await pollRecentAIEvents(1)).toBe(true)
            expect(listSpy).toHaveBeenCalledTimes(1)

            listSpy.mockResolvedValue({ results: [], count: 0 } as any)
            jest.spyOn(api, 'query').mockResolvedValue({ results: [] } as any)
            expect(await pollRecentAIEvents(2)).toBe(false)
            expect(listSpy).toHaveBeenCalledTimes(2)
        })

        it('resolves false instead of rejecting when the check fails, and recovers on the next poll', async () => {
            const listSpy = jest.spyOn(api.eventDefinitions, 'list').mockRejectedValueOnce(new Error('network down'))
            await expect(pollRecentAIEvents(3)).resolves.toBe(false)

            listSpy.mockResolvedValue({
                results: [{ id: '1', name: '$ai_generation', last_seen_at: dayjs().subtract(1, 'day').toISOString() }],
                count: 1,
            } as any)
            await expect(pollRecentAIEvents(3)).resolves.toBe(true)
        })
    })
})
