import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AI_EVENT_NAMES, hasRecentAIEvents } from './aiEventsUtils'

describe('aiEventsUtils', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    describe('AI_EVENT_NAMES', () => {
        it('should contain all expected AI event names', () => {
            expect(AI_EVENT_NAMES).toEqual(['$ai_generation', '$ai_trace', '$ai_span', '$ai_embedding'])
        })
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
            const staleDate = dayjs().subtract(60, 'day').toISOString()

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
