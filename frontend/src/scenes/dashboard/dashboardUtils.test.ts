import posthog from 'posthog-js'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

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
    getInsightWithRetry,
    isWidgetTileVisibleOnPlacement,
    parseURLFilters,
    parseURLVariables,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    shouldSharedDashboardAutoForceForStaleTime,
} from './dashboardUtils'

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

    it.each<[string, number, number | undefined]>([
        ['a deterministic 400 (e.g. query validation error)', 1, 400],
        ['a 429 (rate limited)', MAX_ATTEMPTS, 429],
        ['a 500 (transient server error)', MAX_ATTEMPTS, 500],
        ['a network failure without a status', MAX_ATTEMPTS, undefined],
    ])('on %s, requests %i time(s) before throwing', async (_, expectedAttempts, status) => {
        const getResponseSpy = jest.spyOn(api, 'getResponse').mockRejectedValue(new ApiError('some error', status))

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
        await Promise.all([expect(request).rejects.toThrow('some error'), jest.runAllTimersAsync()])
        expect(getResponseSpy).toHaveBeenCalledTimes(expectedAttempts)
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

    describe.each([
        ['blocking retry', 2],
        ['async fallback', 1],
    ] as const)('%s recovery', (_path, maxAttempts) => {
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
            jest.spyOn(api.queryStatus, 'get').mockResolvedValue({
                query_status: { ...capacityStatus, error: false, error_code: null, error_message: null },
            })

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
        })
    })

    it('reads the cached result when the status of its async run expired while the tab was hidden', async () => {
        const rateLimited = {
            ...insight,
            result: null,
            query_status: { id: 'cache_1_abc', error: true, error_message: 'concurrency_limit_exceeded' },
        }
        jest.spyOn(api, 'getResponse').mockResolvedValue({ json: async () => rateLimited } as Response)
        const getSpy = jest
            .spyOn(api, 'get')
            .mockResolvedValueOnce({ ...insight, result: null, query_status: { id: 'cache_1_abc', complete: false } })
            .mockResolvedValueOnce({ ...insight, result: ['from the cache'], query_status: null })
        jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce(new ApiError('Query not found', 404))

        await expect(
            getInsightWithRetry(
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
        ).resolves.toMatchObject({ result: ['from the cache'] })
        expect(getSpy.mock.calls[1][0]).toContain('refresh=async')
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
