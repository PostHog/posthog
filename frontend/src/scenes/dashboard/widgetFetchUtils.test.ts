import type { DashboardTile, QueryBasedInsightModel } from '~/types'

import { chunkTileIds, findNewlyAddedWidgetTiles } from './widgetFetchUtils'

describe('widgetFetchUtils', () => {
    const widgetTile = (id: number): DashboardTile<QueryBasedInsightModel> => ({
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
