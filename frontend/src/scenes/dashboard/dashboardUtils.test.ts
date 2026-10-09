import posthog from 'posthog-js'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { ConcurrencyController } from 'lib/utils/concurrencyController'

import { BreakdownFilter, DashboardFilter, HogQLVariable, QueryStatus } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    InsightModel,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import {
    dashboardSearchParamsFromOverrides,
    dashboardTemplateForExport,
    dashboardToSaveableTemplate,
    searchParamsWithUrlFilters,
    getDashboardTileDisplayName,
    getInsightQueryError,
    getInsightWithRetry,
    isWidgetTileVisibleOnPlacement,
    parseURLFilters,
    parseURLVariables,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    shouldSharedDashboardAutoForceForStaleTime,
} from './dashboardUtils'

jest.unmock('lib/utils/concurrencyController')

describe('searchParamsWithUrlFilters', () => {
    const propertyFilter: AnyPropertyFilter[] = [
        {
            key: '$browser',
            value: 'Chrome',
            type: PropertyFilterType.Event,
            operator: PropertyOperator.Exact,
        },
    ]
    const breakdownFilter: BreakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }

    it.each([
        ['property filter', { properties: [] }, { properties: propertyFilter }],
        ['breakdown', { breakdown_filter: null }, { breakdown_filter: breakdownFilter }],
    ])('keeps an empty %s override that clears a saved value', (_name, filters, persistedFilters) => {
        const searchParams = searchParamsWithUrlFilters({}, filters, persistedFilters)

        expect(parseURLFilters(searchParams)).toEqual(filters)
    })

    it('removes an empty override when the dashboard has no saved filters', () => {
        const searchParams = searchParamsWithUrlFilters(
            { [SEARCH_PARAM_FILTERS_KEY]: JSON.stringify({ properties: propertyFilter }) },
            { properties: [] }
        )

        expect(searchParams[SEARCH_PARAM_FILTERS_KEY]).toBeUndefined()
    })

    it('keeps an explicit date mode override', () => {
        const searchParams = searchParamsWithUrlFilters({}, { explicitDate: false }, { explicitDate: true })

        expect(parseURLFilters(searchParams)).toEqual({ explicitDate: false })
    })

    it('keeps an override that clears an external filter', () => {
        const searchParams = searchParamsWithUrlFilters({}, { properties: [] }, { properties: propertyFilter })

        expect(parseURLFilters(searchParams)).toEqual({ properties: [] })
    })
})

describe('getDashboardTileDisplayName', () => {
    it('uses widget header title when no custom name is set', () => {
        const tile: DashboardTile = {
            id: 1,
            widget: { id: '1', widget_type: 'error_tracking_list', config: {} },
            layouts: {},
            color: null,
        }

        expect(getDashboardTileDisplayName(tile)).toBe('Top issues')
    })

    it('uses custom widget name when set', () => {
        const tile: DashboardTile = {
            id: 1,
            widget: { id: '1', widget_type: 'error_tracking_list', config: {}, name: 'Critical errors' },
            layouts: {},
            color: null,
        }

        expect(getDashboardTileDisplayName(tile)).toBe('Critical errors')
    })
})

describe('dashboardToSaveableTemplate', () => {
    it('serializes a button tile with a BUTTON type discriminator', () => {
        const dashboard = {
            name: 'My dashboard',
            description: '',
            filters: {},
            tags: [],
            tiles: [
                {
                    id: 1,
                    button_tile: {
                        id: '1',
                        url: '/replay/home',
                        text: 'Watch replays',
                        placement: 'left',
                        style: 'primary',
                    },
                    layouts: {},
                    color: null,
                },
            ],
        } as unknown as DashboardType

        const tile = dashboardToSaveableTemplate(dashboard)?.tiles[0]
        expect(tile).toMatchObject({
            type: 'BUTTON',
            button_tile: { url: '/replay/home', text: 'Watch replays' },
        })
    })

    it('preserves display attributes for every tile type', () => {
        const dashboard = {
            name: 'My dashboard',
            description: '',
            filters: {},
            tags: [],
            tiles: [
                {
                    id: 1,
                    text: {
                        body: 'Text',
                        agent_context: 'Use paid plan events for this metric.',
                        last_modified_at: '2024-01-01',
                    },
                    layouts: {},
                    color: null,
                    transparent_background: true,
                },
                {
                    id: 2,
                    insight: { name: 'Insight', query: { kind: 'TrendsQuery' } },
                    layouts: {},
                    color: null,
                    transparent_background: false,
                },
                {
                    id: 3,
                    button_tile: { url: '/insights', text: 'Insights', placement: 'left', style: 'primary' },
                    layouts: {},
                    color: null,
                    transparent_background: true,
                },
                {
                    id: 4,
                    widget: { id: 'widget-1', widget_type: 'todo', config: {} },
                    layouts: {},
                    color: null,
                    transparent_background: false,
                },
            ],
        } as unknown as DashboardType

        expect(dashboardToSaveableTemplate(dashboard)?.tiles).toMatchObject([
            {
                type: 'TEXT',
                body: 'Text',
                agent_context: 'Use paid plan events for this metric.',
                transparent_background: true,
            },
            { type: 'INSIGHT', transparent_background: false },
            { type: 'BUTTON', transparent_background: true },
            { type: 'WIDGET', transparent_background: false },
        ])
        expect(dashboardTemplateForExport(dashboardToSaveableTemplate(dashboard))?.tiles[0]).not.toHaveProperty(
            'agent_context'
        )
        expect(dashboardTemplateForExport(undefined)).toBeNull()
    })
})

describe('isWidgetTileVisibleOnPlacement', () => {
    it.each([
        [DashboardPlacement.Dashboard, true],
        [DashboardPlacement.Public, true],
        [DashboardPlacement.Export, false],
    ])('placement=%s → %s', (placement, expected) => {
        expect(isWidgetTileVisibleOnPlacement(placement)).toBe(expected)
    })
})

describe('parseURLVariables', () => {
    it.each([
        ['a JSON string value', '{"card_name":"Polukranos, Unchained"}', { card_name: 'Polukranos, Unchained' }],
        [
            'an already-parsed object (kea-router auto-parse)',
            { card_name: 'Polukranos, Unchained' },
            { card_name: 'Polukranos, Unchained' },
        ],
    ])('parses %s from search params', (_, input, expected) => {
        const result = parseURLVariables({ [SEARCH_PARAM_QUERY_VARIABLES_KEY]: input })
        expect(result).toEqual(expected)
    })

    it('returns empty object when key is missing', () => {
        expect(parseURLVariables({})).toEqual({})
    })

    it('returns empty object for invalid JSON string', () => {
        const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        const searchParams = {
            [SEARCH_PARAM_QUERY_VARIABLES_KEY]: 'not-json',
        }
        expect(parseURLVariables(searchParams)).toEqual({})
        consoleSpy.mockRestore()
    })
})

describe('parseURLFilters', () => {
    it.each([
        ['a JSON string value', '{"date_from":"-7d"}', { date_from: '-7d' }],
        [
            'an already-parsed object (kea-router auto-parse)',
            { date_from: '-7d', date_to: 'now' },
            { date_from: '-7d', date_to: 'now' },
        ],
    ])('parses %s from search params', (_, input, expected) => {
        const result = parseURLFilters({ [SEARCH_PARAM_FILTERS_KEY]: input })
        expect(result).toEqual(expected)
    })

    it('returns empty object when key is missing', () => {
        expect(parseURLFilters({})).toEqual({})
    })

    it('returns empty object for invalid JSON string', () => {
        const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        const searchParams = {
            [SEARCH_PARAM_FILTERS_KEY]: 'not-json',
        }
        expect(parseURLFilters(searchParams)).toEqual({})
        consoleSpy.mockRestore()
    })
})

describe('dashboardSearchParamsFromOverrides', () => {
    const variableId = '00000000-0000-0000-0000-00000000beef'
    const cardNameVariable = (overrides: Partial<HogQLVariable>): Record<string, HogQLVariable> => ({
        [variableId]: { variableId, code_name: 'card_name', ...overrides },
    })

    it.each<
        [string, Record<string, HogQLVariable> | null, DashboardFilter | null, Record<string, any>, DashboardFilter]
    >([
        [
            'a variable value',
            cardNameVariable({ value: 'Polukranos, Unchained' }),
            null,
            { card_name: 'Polukranos, Unchained' },
            {},
        ],
        ['a variable set to null', cardNameVariable({ value: 'ignored', isNull: true }), null, { card_name: null }, {}],
        ['a filter override', null, { date_from: '-7d' }, {}, { date_from: '-7d' }],
        ['nothing when there are no overrides', null, {}, {}, {}],
    ])(
        'carries %s back into the dashboard URL',
        (_name, variablesOverride, filtersOverride, expectedVariables, expectedFilters) => {
            const searchParams = dashboardSearchParamsFromOverrides(variablesOverride, filtersOverride)

            expect(parseURLVariables(searchParams)).toEqual(expectedVariables)
            expect(parseURLFilters(searchParams)).toEqual(expectedFilters)
        }
    )
})

describe('getInsightWithRetry', () => {
    const insight = { id: 300, short_id: 'abc123', name: 'Test insight' } as InsightModel
    const MAX_ATTEMPTS = 3
    const capacityStatus: QueryStatus = {
        id: 'q',
        team_id: 1,
        query_async: true,
        complete: true,
        error: true,
        error_code: 'rate_limited',
        error_message: 'Queries are a little too busy right now. Please try again later.',
    }
    const insightResponse = (value: Partial<InsightModel> | null): Response =>
        new Response(JSON.stringify(value), { status: 200 })

    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it.each([429, 503])('honors retry guidance from %s before requesting again', async (status) => {
        const onCapacityWaitChange = jest.fn()
        const getResponse = jest.spyOn(api, 'getResponse')
        getResponse.mockRejectedValueOnce(new ApiError('Busy', status, new Headers({ 'Retry-After': '47' })))
        getResponse.mockResolvedValue(insightResponse({ ...insight, result: [] }))

        const request = getInsightWithRetry(1, insight, 60, 'q', 'blocking', { onCapacityWaitChange })
        await jest.advanceTimersByTimeAsync(46_999)
        expect(getResponse).toHaveBeenCalledTimes(1)
        expect(onCapacityWaitChange.mock.calls).toEqual([[true]])
        await jest.advanceTimersByTimeAsync(1)
        expect((await request)?.result).toEqual([])
        expect(getResponse).toHaveBeenCalledTimes(2)
        expect(onCapacityWaitChange.mock.calls).toEqual([[true], [false]])
    })

    it.each([
        { name: 'missing hint', retryAfter: undefined },
        { name: 'negative hint', retryAfter: -5 },
        { name: 'non-finite hint', retryAfter: Number.POSITIVE_INFINITY },
    ])('uses jittered exponential backoff for $name', async ({ retryAfter }) => {
        jest.spyOn(Math, 'random').mockReturnValue(0.5)
        const getResponse = jest
            .spyOn(api, 'getResponse')
            .mockResolvedValueOnce(
                insightResponse({
                    ...insight,
                    result: null,
                    query_status: { ...capacityStatus, retry_after: retryAfter },
                })
            )
            .mockResolvedValueOnce(
                insightResponse({
                    ...insight,
                    result: null,
                    query_status: { ...capacityStatus, retry_after: retryAfter },
                })
            )
            .mockResolvedValue(insightResponse({ ...insight, result: [] }))

        const request = getInsightWithRetry(
            1,
            insight,
            60,
            'q',
            'blocking',
            undefined,
            undefined,
            undefined,
            undefined,
            5,
            1000
        )
        await jest.advanceTimersByTimeAsync(749)
        expect(getResponse).toHaveBeenCalledTimes(1)
        await jest.advanceTimersByTimeAsync(1)
        expect(getResponse).toHaveBeenCalledTimes(2)
        await jest.advanceTimersByTimeAsync(1499)
        expect(getResponse).toHaveBeenCalledTimes(2)
        await jest.advanceTimersByTimeAsync(1)
        expect((await request)?.result).toEqual([])
    })

    it.each(['429', '503'])('falls back to jitter for a malformed %s Retry-After', async (status) => {
        jest.spyOn(Math, 'random').mockReturnValue(0.5)
        const getResponse = jest
            .spyOn(api, 'getResponse')
            .mockRejectedValueOnce(new ApiError('Busy', Number(status), new Headers({ 'Retry-After': 'later' })))
            .mockResolvedValue(insightResponse({ ...insight, result: [] }))
        const request = getInsightWithRetry(
            1,
            insight,
            60,
            'q',
            'blocking',
            undefined,
            undefined,
            undefined,
            undefined,
            5,
            1000
        )
        await jest.advanceTimersByTimeAsync(749)
        expect(getResponse).toHaveBeenCalledTimes(1)
        await jest.advanceTimersByTimeAsync(1)
        expect((await request)?.result).toEqual([])
    })

    it('waits out a tile cooldown, then retries the blocking request before any async fallback', async () => {
        const onCapacityWaitChange = jest.fn()
        const getResponse = jest
            .spyOn(api, 'getResponse')
            .mockResolvedValueOnce(
                insightResponse({ ...insight, result: null, query_status: { ...capacityStatus, retry_after: 15 } })
            )
            .mockResolvedValue(insightResponse({ ...insight, result: [] }))
        const get = jest.spyOn(api, 'get')
        const request = getInsightWithRetry(1, insight, 60, 'q', 'blocking', { onCapacityWaitChange })
        await jest.advanceTimersByTimeAsync(14_999)
        expect(getResponse).toHaveBeenCalledTimes(1)
        expect(onCapacityWaitChange.mock.calls).toEqual([[true]])
        await jest.advanceTimersByTimeAsync(1)
        expect((await request)?.result).toEqual([])
        expect(getResponse).toHaveBeenCalledTimes(2)
        expect(get).not.toHaveBeenCalled()
    })

    it.each([
        { name: 'a 429 hint longer than the budget', status: 429, retryAfter: '120', expectedRequests: 1 },
        { name: 'a 503 hint longer than the budget', status: 503, retryAfter: '120', expectedRequests: 1 },
        { name: 'repeated 503 hints', status: 503, retryAfter: '30', expectedRequests: 2 },
    ])('stops HTTP retries within the retry budget for $name', async ({ status, retryAfter, expectedRequests }) => {
        const onCapacityWaitChange = jest.fn()
        const error = new ApiError('Busy', status, new Headers({ 'Retry-After': retryAfter }))
        const getResponse = jest.spyOn(api, 'getResponse').mockRejectedValue(error)
        const request = getInsightWithRetry(
            1,
            insight,
            60,
            'q',
            'blocking',
            { onCapacityWaitChange },
            undefined,
            undefined,
            undefined,
            5,
            1000,
            50_000
        )
        await Promise.all([expect(request).rejects.toBe(error), jest.runAllTimersAsync()])
        expect(getResponse).toHaveBeenCalledTimes(expectedRequests)
        expect(onCapacityWaitChange.mock.calls).toEqual(expectedRequests === 1 ? [] : [[true], [false]])
    })

    it('does not retry when a suspended tab resumes after the retry deadline', async () => {
        let elapsedMs = 0
        jest.spyOn(performance, 'now').mockImplementation(() => elapsedMs)
        const getResponse = jest
            .spyOn(api, 'getResponse')
            .mockResolvedValue(
                insightResponse({ ...insight, result: null, query_status: { ...capacityStatus, retry_after: 30 } })
            )
        const request = getInsightWithRetry(1, insight, 60, 'q', 'blocking')
        await jest.advanceTimersByTimeAsync(1)
        elapsedMs = 100_000
        await jest.runAllTimersAsync()
        expect((await request)?.query_status?.error).toBe(true)
        expect(getResponse).toHaveBeenCalledTimes(1)
    })

    it.each([
        { name: 'a long hint', retryAfter: 120, responseMs: 0 },
        { name: 'time spent awaiting responses', retryAfter: 30, responseMs: 25_000 },
    ])('stops retrying within its elapsed budget for $name', async ({ retryAfter, responseMs }) => {
        jest.spyOn(lemonToast, 'error').mockImplementation()
        const failedInsight = { ...insight, result: null, query_status: { ...capacityStatus, retry_after: retryAfter } }
        const getResponse = jest.spyOn(api, 'getResponse').mockImplementation(async () => {
            jest.advanceTimersByTime(responseMs)
            return insightResponse(failedInsight)
        })
        const get = jest.spyOn(api, 'get').mockResolvedValue({})
        const request = getInsightWithRetry(
            1,
            insight,
            60,
            'q',
            'blocking',
            undefined,
            undefined,
            undefined,
            undefined,
            5,
            1000,
            50_000
        )
        await jest.runAllTimersAsync()
        expect((await request)?.query_status).toMatchObject({ error: true, retry_after: retryAfter })
        expect(getResponse).toHaveBeenCalledTimes(1)
        expect(get).not.toHaveBeenCalled()
    })

    it('starts the retry budget when the first queued request actually begins', async () => {
        const getResponse = jest
            .spyOn(api, 'getResponse')
            .mockRejectedValueOnce(new ApiError('Busy', 503, new Headers({ 'Retry-After': '30' })))
            .mockResolvedValueOnce(insightResponse({ ...insight, result: [] }))
        let requests = 0
        const request = getInsightWithRetry(1, insight, 60, 'q', 'blocking', {
            runRequest: async (send) => {
                if (requests++ === 0) {
                    jest.advanceTimersByTime(120_000)
                }
                return send()
            },
        })

        await jest.runAllTimersAsync()
        expect((await request)?.result).toEqual([])
        expect(getResponse).toHaveBeenCalledTimes(2)
    })

    it.each(['http', 'insight', 'async fallback'] as const)(
        'does not send a %s capacity retry if its budget expires in the request queue',
        async (path) => {
            jest.spyOn(lemonToast, 'error').mockImplementation()
            const error = new ApiError('Busy', 503, new Headers({ 'Retry-After': '30' }))
            const failedInsight = { ...insight, result: null, query_status: { ...capacityStatus, retry_after: 30 } }
            const getResponse = jest.spyOn(api, 'getResponse').mockImplementation(async () => {
                if (path === 'http') {
                    throw error
                }
                return insightResponse(failedInsight)
            })
            const get = jest.spyOn(api, 'get')
            const getStatus = jest.spyOn(api.queryStatus, 'get')
            let requests = 0
            const request = getInsightWithRetry(
                1,
                insight,
                60,
                'q',
                'blocking',
                {
                    runRequest: async (send) => {
                        if (requests++ > 0) {
                            jest.advanceTimersByTime(120_000)
                        }
                        return send()
                    },
                },
                undefined,
                undefined,
                undefined,
                path === 'async fallback' ? 1 : 5
            ).catch((error: unknown) => error)

            await jest.runAllTimersAsync()
            expect(await request).toMatchObject(path === 'http' ? error : failedInsight)
            expect(getResponse).toHaveBeenCalledTimes(1)
            expect(get).not.toHaveBeenCalled()
            expect(getStatus).not.toHaveBeenCalled()
        }
    )

    it.each(['before first request', 'during backoff', 'before async fallback'] as const)(
        'cancels %s without sending another request',
        async (stage) => {
            const controller = new AbortController()
            const onCapacityWaitChange = jest.fn()
            const getResponse = jest
                .spyOn(api, 'getResponse')
                .mockResolvedValue(
                    insightResponse({ ...insight, result: null, query_status: { ...capacityStatus, retry_after: 30 } })
                )
            const get = jest.spyOn(api, 'get').mockResolvedValue({})
            if (stage === 'before first request') {
                controller.abort()
            }
            const request = getInsightWithRetry(
                1,
                insight,
                60,
                'q',
                'blocking',
                { signal: controller.signal, onCapacityWaitChange },
                undefined,
                undefined,
                undefined,
                stage === 'before async fallback' ? 1 : 5
            )
            const outcome = request.catch((error: unknown) => error)
            await jest.advanceTimersByTimeAsync(1)
            controller.abort()
            expect(await outcome).toMatchObject({ name: 'AbortError' })
            await jest.runAllTimersAsync()
            expect(getResponse).toHaveBeenCalledTimes(stage === 'before first request' ? 0 : 1)
            expect(get).not.toHaveBeenCalled()
            expect(onCapacityWaitChange.mock.calls).toEqual(stage === 'before first request' ? [] : [[true], [false]])
        }
    )

    it.each<[string, number, number | undefined]>([
        ['a deterministic 400 (e.g. query validation error)', 1, 400],
        ['a 429 (rate limited)', MAX_ATTEMPTS, 429],
        ['a 500 (transient server error)', MAX_ATTEMPTS, 500],
        ['a network failure without a status', MAX_ATTEMPTS, undefined],
    ])('on %s, requests %i time(s) before throwing', async (_, expectedAttempts, status) => {
        const onCapacityWaitChange = jest.fn()
        const getResponseSpy = jest.spyOn(api, 'getResponse').mockRejectedValue(new ApiError('some error', status))

        const request = getInsightWithRetry(
            1,
            insight,
            60,
            'query-id',
            'blocking',
            { onCapacityWaitChange },
            undefined,
            undefined,
            undefined,
            MAX_ATTEMPTS,
            1
        )
        await Promise.all([expect(request).rejects.toThrow('some error'), jest.runAllTimersAsync()])
        expect(getResponseSpy).toHaveBeenCalledTimes(expectedAttempts)
        expect(onCapacityWaitChange.mock.calls).toEqual(status === 429 ? [[true], [false], [true], [false]] : [])
    })

    it.each([
        ['a structured capacity code', 'rate_limited', capacityStatus.error_message],
        ['a legacy concurrency response', 'concurrency_limit_exceeded', 'concurrency_limit_exceeded'],
    ])('retries %s', async (_name, error_code, error_message) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const getResponseSpy = jest
            .spyOn(api, 'getResponse')
            .mockResolvedValueOnce(
                insightResponse({
                    ...insight,
                    result: null,
                    query_status: { ...capacityStatus, error_code, error_message },
                })
            )
            .mockResolvedValueOnce(insightResponse({ ...insight, result: [{ count: 1 }] }))

        const request = getInsightWithRetry(
            1,
            insight,
            60,
            'query-id',
            'blocking',
            undefined,
            undefined,
            undefined,
            undefined,
            MAX_ATTEMPTS,
            1
        )
        await jest.runAllTimersAsync()
        const result = await request

        expect(getResponseSpy).toHaveBeenCalledTimes(2)
        expect(result?.result).toEqual([{ count: 1 }])
        expect(capture).toHaveBeenCalledWith(
            'dashboard tile recovered from capacity error',
            { insight_short_id: 'abc123', dashboard_id: 60, attempts: 1 },
            undefined
        )
    })

    it.each([false, true])('limits async status requests too (expired status: %s)', async (expiredStatus) => {
        const concurrency = new ConcurrencyController(4)
        let priority = 0
        let activePolls = 0
        let peakPolls = 0
        let releasePolls!: () => void
        const pendingPolls = new Promise<void>((resolve) => {
            releasePolls = resolve
        })
        jest.spyOn(api, 'getResponse').mockImplementation(async (url) =>
            insightResponse({
                ...insight,
                result: url.includes('refresh=force_cache') ? [] : null,
                query_status: url.includes('refresh=force_cache') ? undefined : capacityStatus,
            })
        )
        jest.spyOn(api, 'get').mockImplementation(async (url) => ({
            ...insight,
            query_status: {
                ...capacityStatus,
                id: new URL(url, 'http://localhost').searchParams.get('client_query_id'),
                complete: false,
                error: false,
            },
        }))
        const expiredQueries = new Set<string>()
        jest.spyOn(api.queryStatus, 'get').mockImplementation(async (queryId) => {
            if (expiredStatus && !expiredQueries.has(queryId)) {
                expiredQueries.add(queryId)
                throw new ApiError('Query not found', 404)
            }
            activePolls++
            peakPolls = Math.max(peakPolls, activePolls)
            await pendingPolls
            activePolls--
            return {
                query_status: { ...capacityStatus, error: false, error_code: null, error_message: null },
            }
        })

        const requests = Array.from({ length: 6 }, (_, index) => {
            const controller = new AbortController()
            return getInsightWithRetry(
                1,
                { ...insight, id: insight.id + index },
                60,
                `query-${index}`,
                'blocking',
                {
                    signal: controller.signal,
                    runRequest: (fn) => concurrency.run({ fn, priority: priority++, abortController: controller }),
                },
                undefined,
                undefined,
                undefined,
                1,
                1
            )
        })
        try {
            await jest.advanceTimersByTimeAsync(1000)
            expect(activePolls).toBe(4)
        } finally {
            releasePolls()
            await jest.runAllTimersAsync()
            const results = await Promise.all(requests)
            expect(results.map((result) => result?.result)).toEqual(Array(6).fill([]))
        }
        expect(peakPolls).toBe(4)
    })

    describe.each([
        ['blocking retry', 2, false],
        ['async fallback', 1, false],
        ['expired async fallback', 1, true],
    ] as const)('%s recovery', (_path, maxAttempts, expiredStatus) => {
        it.each<{ name: string; response: Partial<InsightModel> | null; recovered: boolean; hasError: boolean }>([
            {
                name: 'a usable result',
                response: { ...insight, result: [{ count: 1 }] },
                recovered: true,
                hasError: false,
            },
            { name: 'an empty result', response: { ...insight, result: [] }, recovered: true, hasError: false },
            {
                name: 'a failed calculation',
                response: {
                    ...insight,
                    result: null,
                    query_status: { ...capacityStatus, error_code: 'hogql_error', error_message: 'Invalid query' },
                },
                recovered: false,
                hasError: true,
            },
            {
                name: 'an error with results',
                response: {
                    ...insight,
                    result: [],
                    query_status: { ...capacityStatus, error_code: 'hogql_error', error_message: 'Invalid query' },
                },
                recovered: false,
                hasError: true,
            },
            { name: 'a missing result', response: { ...insight, result: null }, recovered: false, hasError: false },
            { name: 'no insight', response: null, recovered: false, hasError: maxAttempts === 1 },
        ])('records recovery only for usable data: $name', async ({ response, recovered, hasError }) => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            jest.spyOn(lemonToast, 'error').mockImplementation()
            jest.spyOn(api, 'getResponse')
                .mockResolvedValueOnce(insightResponse({ ...insight, result: null, query_status: capacityStatus }))
                .mockResolvedValueOnce(insightResponse(response))
            jest.spyOn(api, 'get').mockResolvedValue({
                ...insight,
                query_status: {
                    ...capacityStatus,
                    complete: false,
                    error: false,
                    error_code: null,
                    error_message: null,
                },
            })
            const statusSpy = jest.spyOn(api.queryStatus, 'get').mockResolvedValue({
                query_status: { ...capacityStatus, error: false, error_code: null, error_message: null },
            })
            if (expiredStatus) {
                statusSpy.mockRejectedValueOnce(new ApiError('Query not found', 404))
            }

            const request = getInsightWithRetry(
                1,
                insight,
                60,
                'query-id',
                'blocking',
                undefined,
                undefined,
                undefined,
                undefined,
                maxAttempts,
                1
            )
            await jest.runAllTimersAsync()
            const result = await request

            expect(
                capture.mock.calls.filter(([event]) => event === 'dashboard tile recovered from capacity error')
            ).toHaveLength(recovered ? 1 : 0)
            expect(result?.result ?? null).toEqual(response?.result ?? null)
            expect(Boolean(result?.query_status?.error)).toBe(hasError)
            if (expiredStatus) {
                expect(capture.mock.calls.filter(([event]) => event === 'query rerun after status expired')).toEqual([
                    ['query rerun after status expired', { source: 'dashboard_tile', recovered }, undefined],
                ])
            }
        })
    })

    it.each(['failed status', 'failed cache fetch', 'cancelled cache fetch'] as const)(
        'does not count a %s as recovery after expiry',
        async (failure) => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            jest.spyOn(lemonToast, 'error').mockImplementation()
            const cancelled = failure === 'cancelled cache fetch'
            const cacheError = cancelled ? new DOMException('Aborted', 'AbortError') : new ApiError('Unavailable', 503)
            const getResponse = jest
                .spyOn(api, 'getResponse')
                .mockResolvedValueOnce(insightResponse({ ...insight, result: null, query_status: capacityStatus }))
                .mockRejectedValueOnce(cacheError)
            jest.spyOn(api, 'get').mockResolvedValue({
                ...insight,
                query_status: { ...capacityStatus, complete: false, error: false },
            })
            jest.spyOn(api.queryStatus, 'get')
                .mockRejectedValueOnce(new ApiError('Query not found', 404))
                .mockResolvedValueOnce({ query_status: { ...capacityStatus, error: failure === 'failed status' } })

            const request = getInsightWithRetry(
                1,
                insight,
                60,
                'query-id',
                'blocking',
                undefined,
                undefined,
                undefined,
                undefined,
                1,
                1
            )
            const outcome = Promise.allSettled([request])
            await jest.runAllTimersAsync()
            expect((await outcome)[0].status).toBe(cancelled ? 'rejected' : 'fulfilled')
            expect(getResponse).toHaveBeenCalledTimes(failure === 'failed status' ? 1 : 2)
            expect(capture.mock.calls.filter(([event]) => event === 'query rerun after status expired')).toEqual(
                cancelled
                    ? []
                    : [['query rerun after status expired', { source: 'dashboard_tile', recovered: false }, undefined]]
            )
            expect(
                capture.mock.calls.filter(([event]) => event === 'dashboard tile recovered from capacity error')
            ).toHaveLength(0)
        }
    )

    it.each([
        { description: 'available', cachedResult: ['from the cache'], queryStatus: null },
        { description: 'missing', cachedResult: null, queryStatus: null },
        {
            description: 'available while refreshing',
            cachedResult: ['from the cache'],
            queryStatus: { id: 'refresh', complete: false, error: false },
        },
        {
            description: 'empty while refreshing',
            cachedResult: [],
            queryStatus: { id: 'refresh', complete: false, error: false },
        },
    ])('handles a cached result that is $description after status expiry', async ({ cachedResult, queryStatus }) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        jest.spyOn(lemonToast, 'error').mockImplementation()
        const rateLimited = {
            ...insight,
            result: null,
            query_status: { id: 'cache_1_abc', error: true, error_message: 'concurrency_limit_exceeded' },
        }
        jest.spyOn(api, 'getResponse').mockResolvedValue({ json: async () => rateLimited } as Response)
        const getSpy = jest
            .spyOn(api, 'get')
            .mockResolvedValueOnce({ ...insight, result: null, query_status: { id: 'cache_1_abc', complete: false } })
            .mockResolvedValueOnce({ ...insight, result: cachedResult, query_status: queryStatus })
        const statusSpy = jest
            .spyOn(api.queryStatus, 'get')
            .mockRejectedValueOnce(new ApiError('Query not found', 404))
            .mockRejectedValue(new ApiError('Background refresh unavailable', 503))

        const request = getInsightWithRetry(
            1,
            insight,
            60,
            'query-id',
            'blocking',
            undefined,
            undefined,
            undefined,
            undefined,
            1,
            1
        )
        await jest.runAllTimersAsync()
        const result = await request
        expect(result?.result).toEqual(cachedResult)
        expect(Boolean(result?.query_status?.error)).toBe(cachedResult === null)
        expect(getSpy.mock.calls[1][0]).toContain('refresh=async')
        expect(statusSpy).toHaveBeenCalledTimes(1)
        expect(
            capture.mock.calls.filter(([event]) => event === 'dashboard tile recovered from capacity error')
        ).toHaveLength(cachedResult === null ? 0 : 1)
        expect(capture).toHaveBeenCalledWith(
            'query rerun after status expired',
            { source: 'dashboard_tile', recovered: cachedResult !== null },
            undefined
        )
    })
})

describe('shouldSharedDashboardAutoForceForStaleTime', () => {
    it.each<[string, dayjs.Dayjs | null, boolean]>([
        ['last refresh is null', null, false],
        ['last refresh is an invalid Dayjs', dayjs(new Date(Number.NaN)), false],
        ['stalest tile is newer than the auto-force threshold', dayjs().subtract(29, 'minute'), false],
        ['stalest tile is older than the auto-force threshold', dayjs().subtract(31, 'minute'), true],
    ])('when %s, returns expected result', (_, input, expected) => {
        expect(shouldSharedDashboardAutoForceForStaleTime(input)).toBe(expected)
    })

    describe('with fixed clock', () => {
        beforeEach(() => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2026-06-15T12:00:00.000Z'))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it.each<[string, string, boolean]>([
            ['at exactly the threshold age (30 minutes)', '2026-06-15T11:30:00.000Z', true],
            ['just under the threshold', '2026-06-15T11:31:00.000Z', false],
        ])('when %s, returns expected result', (_, isoTime, expected) => {
            expect(shouldSharedDashboardAutoForceForStaleTime(dayjs(isoTime))).toBe(expected)
        })
    })
})

describe('getInsightQueryError', () => {
    it.each([
        ['clickhouse_memory_limit_exceeded', 513],
        ['invalid_query', 400],
    ])('maps error code %s to status %s', (errorCode, expectedStatus) => {
        const error = getInsightQueryError({
            query_status: {
                id: 'query-id',
                error: true,
                error_message: 'Query ran out of memory',
                error_code: errorCode,
            },
        } as unknown as InsightModel)

        expect(error?.status).toBe(expectedStatus)
        expect(error?.data?.code).toBe(errorCode)
    })

    it('reads the memory code out of the error message when the status field is absent', () => {
        const error = getInsightQueryError({
            query_status: {
                id: 'query-id',
                error: true,
                error_message:
                    "[ErrorDetail(string='Query ran out of memory', code='clickhouse_memory_limit_exceeded')]",
            },
        } as unknown as InsightModel)

        expect(error?.status).toBe(513)
        expect(error?.data?.code).toBe('clickhouse_memory_limit_exceeded')
    })

    it('returns null when the query did not error', () => {
        expect(getInsightQueryError({} as InsightModel)).toBeNull()
    })
})
