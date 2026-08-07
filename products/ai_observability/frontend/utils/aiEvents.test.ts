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
        // Any non-stale `$ai_*` definition should short-circuit to the dashboard. Cover events that
        // the old four-name allowlist dropped ($ai_metric, $ai_feedback, $ai_evaluation) so a
        // project instrumented with only those isn't sent back to onboarding.
        it.each(['$ai_generation', '$ai_trace', '$ai_metric', '$ai_feedback', '$ai_evaluation'])(
            'returns true from EventDefinition for %s without querying ClickHouse',
            async (eventName) => {
                const recentDate = dayjs().subtract(1, 'day').toISOString()

                useMocks({
                    get: {
                        '/api/projects/:team_id/event_definitions/': {
                            results: [{ id: '1', name: eventName, last_seen_at: recentDate }],
                            count: 1,
                        },
                    },
                })

                const queryApiSpy = jest.spyOn(api, 'query')

                const result = await hasRecentAIEvents()

                expect(result).toBe(true)
                expect(queryApiSpy).not.toHaveBeenCalled()
            }
        )

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
                                name: '$pageview',
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
