import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'

import { DashboardPlacement, DashboardTile, DashboardType, InsightModel, QueryBasedInsightModel } from '~/types'

import {
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
    const propertyFilter = [{ key: '$browser', value: 'Chrome', type: 'event' }]
    const breakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }

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
        const tile: DashboardTile<QueryBasedInsightModel> = {
            id: 1,
            widget: { id: '1', widget_type: 'error_tracking_list', config: {} },
            layouts: {},
            color: null,
        }

        expect(getDashboardTileDisplayName(tile)).toBe('Top issues')
    })

    it('uses custom widget name when set', () => {
        const tile: DashboardTile<QueryBasedInsightModel> = {
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
        } as unknown as DashboardType<InsightModel>

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
                    text: { body: 'Text', last_modified_at: '2024-01-01' },
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
        } as unknown as DashboardType<InsightModel>

        expect(dashboardToSaveableTemplate(dashboard)?.tiles).toMatchObject([
            { type: 'TEXT', transparent_background: true },
            { type: 'INSIGHT', transparent_background: false },
            { type: 'BUTTON', transparent_background: true },
            { type: 'WIDGET', transparent_background: false },
        ])
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

describe('getInsightWithRetry', () => {
    const insight = { id: 300, short_id: 'abc123', name: 'Test insight' } as QueryBasedInsightModel
    const MAX_ATTEMPTS = 3

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each<[string, number, number | undefined]>([
        ['a deterministic 400 (e.g. query validation error)', 1, 400],
        ['a 429 (rate limited)', MAX_ATTEMPTS, 429],
        ['a 500 (transient server error)', MAX_ATTEMPTS, 500],
        ['a network failure without a status', MAX_ATTEMPTS, undefined],
    ])('on %s, requests %i time(s) before throwing', async (_, expectedAttempts, status) => {
        const getResponseSpy = jest.spyOn(api, 'getResponse').mockRejectedValue(new ApiError('some error', status))

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
                MAX_ATTEMPTS,
                1
            )
        ).rejects.toThrow('some error')
        expect(getResponseSpy).toHaveBeenCalledTimes(expectedAttempts)
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
