import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { parseErrorMessage, performQuery, pollForResults, queryExportContext } from '~/queries/query'
import { EventsQuery, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { setLatestVersionsOnQuery } from './utils'

describe('query', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query': (req) => {
                    const data = req.body as any
                    if (data.query?.kind === 'HogQLQuery') {
                        return [
                            200,
                            { results: [], clickhouse: 'clickhouse string', hogql: 'hogql string', is_cached: false },
                        ]
                    }
                    if (data.query?.kind === 'EventsQuery' && data.query.select[0] === 'error') {
                        return [500, { detail: 'error' }]
                    }
                    return [200, {}]
                },
            },
        })
        initKeaTests()
    })

    it('can generate events table export context', () => {
        const q: EventsQuery = {
            kind: NodeKind.EventsQuery,
            select: [
                '*',
                'event',
                'person',
                'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                'properties.$lib',
                'timestamp',
            ],
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    operator: PropertyOperator.Exact,
                    value: 'Chrome',
                },
            ],
            limit: 100,
        }
        const actual = queryExportContext(q, {}, false)
        expect(actual).toEqual({
            source: {
                kind: 'EventsQuery',
                limit: 100,
                properties: [
                    {
                        key: '$browser',
                        operator: 'exact',
                        type: 'event',
                        value: 'Chrome',
                    },
                ],
                select: [
                    '*',
                    'event',
                    'person',
                    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                    'properties.$lib',
                    'timestamp',
                ],
            },
        })
    })

    it('emits an event when a query is run', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: EventsQuery = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['timestamp'],
            limit: 100,
        })
        captureSpy.mockClear()
        await performQuery(q)
        const queryCompletedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query completed')
        expect(queryCompletedCalls).toHaveLength(1)
        expect(queryCompletedCalls[0][1]).toMatchObject({ query: q, duration: expect.any(Number) })
    })

    it('emits a specific event on a HogQLQuery', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: HogQLQuery = setLatestVersionsOnQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select * from events',
        })
        captureSpy.mockClear()
        await performQuery(q)
        const queryCompletedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query completed')
        expect(queryCompletedCalls).toHaveLength(1)
        expect(queryCompletedCalls[0][1]).toMatchObject({
            query: q,
            duration: expect.any(Number),
            clickhouse_sql: expect.any(String),
            is_cached: false,
        })
    })

    it('emits an event when a query errors', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: EventsQuery = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['error'],
            limit: 100,
        })
        captureSpy.mockClear()
        await expect(async () => {
            await performQuery(q)
        }).rejects.toThrow(ApiError)

        const queryFailedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query failed')
        expect(queryFailedCalls).toHaveLength(1)
        expect(queryFailedCalls[0][1]).toMatchObject({ query: q, duration: expect.any(Number) })
    })

    describe('pollForResults error message parsing', () => {
        it('parses ErrorDetail list format and extracts message and code', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message:
                            "[ErrorDetail(string='Query exceeded memory limit', code='memory_limit_exceeded')]",
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'Query exceeded memory limit',
                code: 'memory_limit_exceeded',
            })
        })

        it('parses ErrorDetail single format and extracts message and code', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message: "ErrorDetail(string='Database connection failed', code='db_error')",
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'Database connection failed',
                code: 'db_error',
            })
        })

        it('preserves original message when not in ErrorDetail format', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message: 'Simple error message',
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'Simple error message',
            })
        })

        it('handles undefined error message', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {},
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: '',
            })
        })

        it('handles non-string error message', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message: { nested: 'object' },
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: { nested: 'object' },
            })
        })
    })

    describe('parseErrorMessage', () => {
        it('parses ErrorDetail list format', () => {
            const result = parseErrorMessage(
                "[ErrorDetail(string='Query exceeded memory limit', code='memory_limit_exceeded')]"
            )
            expect(result).toEqual({ message: 'Query exceeded memory limit', code: 'memory_limit_exceeded' })
        })

        it('parses ErrorDetail single format', () => {
            const result = parseErrorMessage("ErrorDetail(string='Database connection failed', code='db_error')")
            expect(result).toEqual({ message: 'Database connection failed', code: 'db_error' })
        })

        it('handles plain string messages', () => {
            const result = parseErrorMessage('Simple error message')
            expect(result).toEqual({ message: 'Simple error message', code: null })
        })

        it('handles empty string', () => {
            const result = parseErrorMessage('')
            expect(result).toEqual({ message: '', code: null })
        })

        it('handles undefined', () => {
            const result = parseErrorMessage(undefined)
            expect(result).toEqual({ message: '', code: null })
        })

        it('handles messages with special characters', () => {
            const result = parseErrorMessage(
                "[ErrorDetail(string='Error: Invalid query \"SELECT *\"', code='syntax_error')]"
            )
            expect(result).toEqual({ message: 'Error: Invalid query "SELECT *"', code: 'syntax_error' })
        })

        it('handles messages with single quotes using double quote delimiters', () => {
            // Backend uses double quotes for the string value when the message contains single quotes
            const result = parseErrorMessage("ErrorDetail(string=\"User's query failed\", code='user_error')")
            expect(result).toEqual({
                message: "User's query failed",
                code: 'user_error',
            })
        })

        it('preserves malformed ErrorDetail strings', () => {
            const result = parseErrorMessage("ErrorDetail(string='Incomplete")
            expect(result).toEqual({ message: "ErrorDetail(string='Incomplete", code: null })
        })

        it('handles ErrorDetail with missing code', () => {
            const result = parseErrorMessage("ErrorDetail(string='Error message')")
            expect(result).toEqual({ message: "ErrorDetail(string='Error message')", code: null })
        })

        it('handles ErrorDetail with extra whitespace', () => {
            const result = parseErrorMessage("[ErrorDetail(string='Test error',   code='test_code')]")
            expect(result).toEqual({ message: 'Test error', code: 'test_code' })
        })

        it('parses ErrorDetail with double quotes in list format', () => {
            const result = parseErrorMessage(
                "[ErrorDetail(string=\"Invalid metric configuration: breakdown property 'user_id' does not exist.\", code='invalid')]"
            )
            expect(result).toEqual({
                message: "Invalid metric configuration: breakdown property 'user_id' does not exist.",
                code: 'invalid',
            })
        })

        it('parses ErrorDetail with double quotes in single format', () => {
            const result = parseErrorMessage('ErrorDetail(string="Database error occurred", code=\'db_error\')')
            expect(result).toEqual({ message: 'Database error occurred', code: 'db_error' })
        })

        describe('experiment error messages', () => {
            it('parses memory limit exceeded error', () => {
                const result = parseErrorMessage(
                    "[ErrorDetail(string='This experiment query is using too much memory. Try viewing a shorter time period or contact support for help.', code='memory_limit_exceeded')]"
                )
                expect(result).toEqual({
                    message:
                        'This experiment query is using too much memory. Try viewing a shorter time period or contact support for help.',
                    code: 'memory_limit_exceeded',
                })
            })

            it('parses too many variants error', () => {
                const result = parseErrorMessage(
                    "[ErrorDetail(string='Can\\'t calculate experiment results for more than 10 variants', code='too_much_data')]"
                )
                expect(result).toEqual({
                    message: "Can't calculate experiment results for more than 10 variants",
                    code: 'too_much_data',
                })
            })

            it('parses too few variants error', () => {
                const result = parseErrorMessage(
                    "[ErrorDetail(string='Can\\'t calculate experiment results for less than 2 variants', code='no_data')]"
                )
                expect(result).toEqual({
                    message: "Can't calculate experiment results for less than 2 variants",
                    code: 'no_data',
                })
            })

            it('parses no results validation error', () => {
                const result = parseErrorMessage(
                    '[ErrorDetail(string=\'{"no-control-variant": true, "no-test-variant": false}\', code=\'no-results\')]'
                )
                expect(result).toEqual({
                    message: '{"no-control-variant": true, "no-test-variant": false}',
                    code: 'no-results',
                })
            })

            it('parses validation error without code', () => {
                const result = parseErrorMessage('experiment_id is required')
                expect(result).toEqual({
                    message: 'experiment_id is required',
                    code: null,
                })
            })

            it('parses statistic calculation error', () => {
                const result = parseErrorMessage(
                    'Unable to calculate experiment statistics. Please ensure your experiment has sufficient data and try again.'
                )
                expect(result).toEqual({
                    message:
                        'Unable to calculate experiment statistics. Please ensure your experiment has sufficient data and try again.',
                    code: null,
                })
            })

            it('parses HogQL error message', () => {
                const result = parseErrorMessage(
                    'Unable to process your experiment query. Please check your metric configuration and try again.'
                )
                expect(result).toEqual({
                    message:
                        'Unable to process your experiment query. Please check your metric configuration and try again.',
                    code: null,
                })
            })

            it('parses ClickHouse error message', () => {
                const result = parseErrorMessage('Unable to retrieve experiment data. Please try refreshing the page.')
                expect(result).toEqual({
                    message: 'Unable to retrieve experiment data. Please try refreshing the page.',
                    code: null,
                })
            })

            it('parses zero division error message', () => {
                const result = parseErrorMessage(
                    'Unable to calculate results due to insufficient data. Please wait for more experiment data.'
                )
                expect(result).toEqual({
                    message:
                        'Unable to calculate results due to insufficient data. Please wait for more experiment data.',
                    code: null,
                })
            })

            it('parses maximum breakdowns error', () => {
                const result = parseErrorMessage('Maximum of 3 breakdowns are supported for experiment metrics')
                expect(result).toEqual({
                    message: 'Maximum of 3 breakdowns are supported for experiment metrics',
                    code: null,
                })
            })

            it('parses experiment not found error', () => {
                const result = parseErrorMessage('Experiment with id 123 not found')
                expect(result).toEqual({
                    message: 'Experiment with id 123 not found',
                    code: null,
                })
            })
        })
    })
})
