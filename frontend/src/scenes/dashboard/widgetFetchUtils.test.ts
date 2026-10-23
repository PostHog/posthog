import type { DashboardFilter } from '~/queries/schema/schema-general'
import type { DashboardTile } from '~/types'

import { chunkTileIds, findNewlyAddedWidgetTiles, isWidgetStale, widgetDashboardFilters } from './widgetFetchUtils'

describe('widgetFetchUtils', () => {
    it('treats failed widgets as stale but not loading or missing widgets', () => {
        expect(isWidgetStale(undefined, 1_000_000)).toBe(false)
        expect(isWidgetStale({ error: 'Query failed', fetchedAt: 1_000_000 }, 1_000_000)).toBe(true)
        expect(isWidgetStale({ loading: true, fetchedAt: 1_000_000 }, 1_000_000)).toBe(false)
    })

    const widgetTile = (id: number): DashboardTile => ({
        id,
        widget: { id: String(id), widget_type: 'error_tracking_list', config: {} },
        layouts: {},
        color: null,
    })

    describe('findNewlyAddedWidgetTiles', () => {
        it('returns all tile ids that were not in the previous set', () => {
            const previousTileIds = new Set([7])
            const tiles = [widgetTile(7), widgetTile(9), widgetTile(10)]

            expect(findNewlyAddedWidgetTiles(previousTileIds, tiles).map((tile) => tile.id)).toEqual([9, 10])
        })

        it('does not match an existing tile when multiple widgets share the same type', () => {
            const previousTileIds = new Set([7, 8])
            const tiles = [widgetTile(7), widgetTile(8), widgetTile(9)]

            expect(findNewlyAddedWidgetTiles(previousTileIds, tiles).map((tile) => tile.id)).toEqual([9])
        })

        it('ignores deleted widget tiles', () => {
            const previousTileIds = new Set([7])
            const tiles = [widgetTile(7), { ...widgetTile(9), deleted: true }]

            expect(findNewlyAddedWidgetTiles(previousTileIds, tiles)).toEqual([])
        })

        it('returns empty when no new widget tile exists', () => {
            const previousTileIds = new Set([7])
            expect(findNewlyAddedWidgetTiles(previousTileIds, [widgetTile(7)])).toEqual([])
        })
    })

    describe('widgetDashboardFilters', () => {
        const DATE_KEYS = ['date_from', 'date_to']

        it.each([
            [
                'keeps a cleared filter explicit, so it replaces the saved one',
                {},
                DATE_KEYS,
                { date_from: null, date_to: null },
            ],
            [
                'keeps the widget keys and drops the rest',
                {
                    date_from: '-1h',
                    properties: [],
                    breakdown_filter: {},
                    metricVariables: [{ name: 'window', type: 'interval', values: ['5m'], current: '5m' }],
                },
                DATE_KEYS,
                { date_from: '-1h', date_to: null },
            ],
        ])('%s', (_name, filters, keys, expected) => {
            expect(widgetDashboardFilters(filters as DashboardFilter, keys)).toEqual(expected)
        })
    })

    describe('chunkTileIds', () => {
        it('returns empty array for empty input', () => {
            expect(chunkTileIds([])).toEqual([])
        })

        it('chunks tile ids with default size 4', () => {
            expect(chunkTileIds([1, 2, 3, 4, 5])).toEqual([[1, 2, 3, 4], [5]])
        })

        it('respects custom chunk size', () => {
            expect(chunkTileIds([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
        })
    })
})
