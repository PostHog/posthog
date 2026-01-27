import { Layout } from 'react-grid-layout'

import { calculateDuplicateLayout, calculateLayouts } from 'scenes/dashboard/tileLayouts'

import { DashboardLayoutSize, DashboardTile, QueryBasedInsightModel, TileLayout } from '~/types'

function textTileWithLayout(
    layouts: Record<DashboardLayoutSize, TileLayout>,
    tileId: number = 1
): DashboardTile<QueryBasedInsightModel> {
    return {
        id: tileId,
        text: 'test',
        layouts: layouts,
    } as unknown as DashboardTile<QueryBasedInsightModel>
}

describe('calculating tile layouts', () => {
    it('minimum width and height are added if missing', () => {
        const tiles: DashboardTile<QueryBasedInsightModel>[] = [
            textTileWithLayout({
                sm: { i: '1', x: 0, y: 0, w: 1, h: 1 },
                xs: { i: '1', x: 0, y: 0, w: 1, h: 1 },
            }),
        ]
        expect(calculateLayouts(tiles)).toEqual({
            sm: [{ i: '1', x: 0, y: 0, w: 1, h: 1, minW: 1, minH: 1 }],
            xs: [{ i: '1', x: 0, y: 0, w: 1, h: 1, minW: 1, minH: 1 }],
        })
    })

    it('when the tiles have only 2-col layouts, 1 col layout is calculated', () => {
        // sm layouts have been re-ordered
        // they are not in creation order when read left to right.
        // but the back-end may send them in creation order
        // we have [ '1 x:{0} y:{0}', '2 x:{6} y:{6}', '3 x:{6} y:{0}', '4 x:{0} y:{6}' ]
        // which sort as [ '1 x:{0} y:{0}', '3 x:{6} y:{0}', '4 x:{0} y:{6}', '2 x:{6} y:{6}' ]
        const smLayouts = [
            { i: '1', x: 0, y: 0, w: 6, h: 6, minW: 3, minH: 2 },
            { i: '2', x: 0, y: 6, w: 6, h: 6, minW: 3, minH: 2 },
            { i: '3', x: 6, y: 6, w: 6, h: 6, minW: 3, minH: 2 },
            { i: '4', x: 6, y: 0, w: 6, h: 6, minW: 3, minH: 2 },
        ]
        const tiles: DashboardTile<QueryBasedInsightModel>[] = [
            textTileWithLayout({ sm: smLayouts[0] } as Record<DashboardLayoutSize, TileLayout>, 1),
            textTileWithLayout({ sm: smLayouts[2] } as Record<DashboardLayoutSize, TileLayout>, 2),
            textTileWithLayout({ sm: smLayouts[3] } as Record<DashboardLayoutSize, TileLayout>, 3),
            textTileWithLayout({ sm: smLayouts[1] } as Record<DashboardLayoutSize, TileLayout>, 4),
        ]

        const actual = calculateLayouts(tiles)

        expect(actual.sm?.map((layout) => layout.i)).toEqual(['1', '3', '4', '2'])
        expect(actual.sm?.map((layout) => layout.x)).toEqual([0, 6, 0, 6])
        expect(actual.sm?.map((layout) => layout.y)).toEqual([0, 0, 6, 6])

        expect(actual.xs?.map((layout) => layout.i)).toEqual(['1', '3', '4', '2'])
        // one col all start at x: 0
        expect(actual.xs?.map((layout) => layout.x)).toEqual([0, 0, 0, 0])
        // one col with equal height of 6 should be
        expect(actual.xs?.map((layout) => layout.y)).toEqual([0, 2, 4, 6])
    })
})

describe('calculateDuplicateLayout', () => {
    const smLayout = (i: string, x: number, y: number, w: number, h: number): Layout => ({ i, x, y, w, h })

    it.each([
        {
            name: 'places to the right when there is room',
            layouts: { sm: [smLayout('1', 0, 0, 6, 5)] },
            tileId: 1,
            expected: {
                duplicateLayouts: { sm: { x: 6, y: 0, w: 6, h: 5 } },
                tilesToUpdate: [],
            },
        },
        {
            name: 'places below when tile is too wide to fit right',
            layouts: { sm: [smLayout('1', 0, 0, 8, 5)] },
            tileId: 1,
            expected: {
                duplicateLayouts: { sm: { x: 0, y: 5, w: 8, h: 5 } },
                tilesToUpdate: [],
            },
        },
        {
            name: 'places below when another tile blocks the right',
            layouts: { sm: [smLayout('1', 0, 0, 6, 5), smLayout('2', 6, 0, 6, 5)] },
            tileId: 1,
            expected: {
                duplicateLayouts: { sm: { x: 0, y: 5, w: 6, h: 5 } },
                tilesToUpdate: [],
            },
        },
        {
            name: 'pushes tiles at or below insertion point down',
            layouts: {
                sm: [smLayout('1', 0, 0, 6, 5), smLayout('2', 6, 0, 6, 5), smLayout('3', 0, 5, 6, 5)],
            },
            tileId: 1,
            expected: {
                duplicateLayouts: { sm: { x: 0, y: 5, w: 6, h: 5 } },
                tilesToUpdate: [{ id: 3, layouts: { sm: { x: 0, y: 10, w: 6, h: 5 }, xs: undefined } }],
            },
        },
        {
            name: 'returns empty result when tile not found',
            layouts: { sm: [smLayout('1', 0, 0, 6, 5)] },
            tileId: 99,
            expected: { duplicateLayouts: {}, tilesToUpdate: [] },
        },
        {
            name: 'returns empty result when layouts are null',
            layouts: null,
            tileId: 1,
            expected: { duplicateLayouts: {}, tilesToUpdate: [] },
        },
    ])('$name', ({ layouts, tileId, expected }) => {
        const result = calculateDuplicateLayout(
            layouts as Partial<Record<DashboardLayoutSize, Layout[]>> | null,
            tileId
        )

        expect(result.duplicateLayouts).toEqual(expected.duplicateLayouts)
        expect(result.tilesToUpdate).toEqual(expected.tilesToUpdate)
    })

    it('includes xs layout for duplicate when original has xs layout', () => {
        const layouts = {
            sm: [smLayout('1', 0, 0, 6, 5)],
            xs: [{ i: '1', x: 0, y: 0, w: 1, h: 5 } as Layout],
        }

        const result = calculateDuplicateLayout(layouts, 1)

        expect(result.duplicateLayouts.sm).toEqual({ x: 6, y: 0, w: 6, h: 5 })
        expect(result.duplicateLayouts.xs).toEqual({ x: 0, y: 5, w: 1, h: 5 })
    })
})
