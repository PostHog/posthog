import { dayjs } from 'lib/dayjs'

import { DashboardPlacement, DashboardTile, DashboardType, InsightShortId, QueryBasedInsightModel } from '~/types'

import {
    getDashboardTileDisplayName,
    isWidgetTileVisibleOnPlacement,
    parseURLFilters,
    parseURLVariables,
    preserveExistingTileResults,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    shouldSharedDashboardAutoForceForStaleTime,
} from './dashboardUtils'

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

describe('preserveExistingTileResults', () => {
    const insightTile = (
        tileId: number,
        shortId: string,
        insightOverrides: Partial<QueryBasedInsightModel> = {}
    ): DashboardTile<QueryBasedInsightModel> =>
        ({
            id: tileId,
            layouts: {},
            color: null,
            insight: {
                id: tileId * 100,
                short_id: shortId as InsightShortId,
                result: null,
                last_refresh: null,
                ...insightOverrides,
            } as QueryBasedInsightModel,
        }) as DashboardTile<QueryBasedInsightModel>

    const dashboardWith = (
        tiles: DashboardTile<QueryBasedInsightModel>[],
        id: number = 1
    ): DashboardType<QueryBasedInsightModel> => ({ id, tiles }) as DashboardType<QueryBasedInsightModel>

    it('copies the previous result into incoming tiles whose result is null', () => {
        const previous = dashboardWith([
            insightTile(1, 'abc', { result: [{ count: 42 }], last_refresh: '2026-06-01T00:00:00Z', is_cached: true }),
        ])
        const incoming = dashboardWith([insightTile(1, 'abc')])

        const merged = preserveExistingTileResults(incoming, previous)

        expect(merged?.tiles?.[0]?.insight).toMatchObject({
            result: [{ count: 42 }],
            last_refresh: '2026-06-01T00:00:00Z',
            is_cached: true,
        })
    })

    it.each([
        [
            'the incoming tile already has a result',
            insightTile(1, 'abc', { result: [{ count: 1 }] }),
            insightTile(1, 'abc', { result: [{ count: 99 }] }),
            [{ count: 99 }],
        ],
        ['the previous tile has no result either', insightTile(1, 'abc'), insightTile(1, 'abc'), null],
        [
            'the tile now holds a different insight',
            insightTile(1, 'abc', { result: [{ count: 1 }] }),
            insightTile(1, 'xyz'),
            null,
        ],
        [
            'the incoming result is an empty array (valid empty result)',
            insightTile(1, 'abc', { result: [{ count: 1 }] }),
            insightTile(1, 'abc', { result: [] }),
            [],
        ],
    ])('keeps the incoming result when %s', (_, previousTile, incomingTile, expectedResult) => {
        const merged = preserveExistingTileResults(dashboardWith([incomingTile]), dashboardWith([previousTile]))

        expect(merged?.tiles?.[0]?.insight?.result).toEqual(expectedResult)
    })

    it('returns incoming unchanged when dashboards have different ids', () => {
        const previous = dashboardWith([insightTile(1, 'abc', { result: [{ count: 1 }] })], 1)
        const incoming = dashboardWith([insightTile(1, 'abc')], 2)

        expect(preserveExistingTileResults(incoming, previous)).toBe(incoming)
    })

    it('returns incoming unchanged when either dashboard is null', () => {
        const dashboard = dashboardWith([insightTile(1, 'abc')])

        expect(preserveExistingTileResults(dashboard, null)).toBe(dashboard)
        expect(preserveExistingTileResults(null, dashboard)).toBe(null)
    })

    it('leaves non-insight tiles untouched', () => {
        const textTile = {
            id: 7,
            layouts: {},
            color: null,
            text: { body: 'hello' },
        } as unknown as DashboardTile<QueryBasedInsightModel>
        const merged = preserveExistingTileResults(dashboardWith([textTile]), dashboardWith([textTile]))

        expect(merged?.tiles?.[0]).toBe(textTile)
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
