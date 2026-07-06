import { Layout, LayoutItem } from 'react-grid-layout'

import { calculateDuplicateLayout, calculateInsertionLayout, calculateLayouts } from 'scenes/dashboard/tileLayouts'

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
            } as Record<DashboardLayoutSize, TileLayout>),
        ]
        expect(calculateLayouts(tiles)).toEqual({
            sm: [{ i: '1', x: 0, y: 0, w: 1, h: 1, minW: 1, minH: 1 }],
            // xs uses the same row height as sm when sm is present
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
        // one col: xs keeps each tile's sm row height (h:6), so y advances by 6 per tile
        expect(actual.xs?.map((layout) => layout.y)).toEqual([0, 6, 12, 18])
    })

    it.each([
        {
            name: 'no sm layout on tile',
            layouts: {} as Record<DashboardLayoutSize, TileLayout>,
            expectedXsH: 2,
        },
        {
            name: 'sm layout without usable h (zero)',
            layouts: { sm: { i: '1', x: 0, y: 0, w: 2, h: 0 } } as Record<DashboardLayoutSize, TileLayout>,
            expectedXsH: 2,
        },
        {
            name: 'sm h is not a number (fallback to text default)',
            layouts: { sm: { i: '1', x: 0, y: 0, w: 2, h: '3' as unknown as number } } as Record<
                DashboardLayoutSize,
                TileLayout
            >,
            expectedXsH: 2,
        },
    ])('xs uses text default row height when $name', ({ layouts, expectedXsH }) => {
        const tiles: DashboardTile<QueryBasedInsightModel>[] = [textTileWithLayout(layouts, 1)]
        const result = calculateLayouts(tiles)
        expect(result.xs?.[0]?.h).toBe(expectedXsH)
    })

    it('xs follows final sm row-major order when some tiles have no stored sm layout', () => {
        const tiles: DashboardTile<QueryBasedInsightModel>[] = [
            textTileWithLayout(
                { sm: { i: '1', x: 0, y: 0, w: 6, h: 5 } } as Record<DashboardLayoutSize, TileLayout>,
                1
            ),
            textTileWithLayout(
                { sm: { i: '2', x: 6, y: 0, w: 6, h: 5 } } as Record<DashboardLayoutSize, TileLayout>,
                2
            ),
            textTileWithLayout(
                { sm: { i: '3', x: 0, y: 5, w: 6, h: 5 } } as Record<DashboardLayoutSize, TileLayout>,
                3
            ),
            textTileWithLayout(
                { sm: { i: '4', x: 6, y: 5, w: 6, h: 5 } } as Record<DashboardLayoutSize, TileLayout>,
                4
            ),
            textTileWithLayout({} as Record<DashboardLayoutSize, TileLayout>, 5),
            textTileWithLayout({} as Record<DashboardLayoutSize, TileLayout>, 6),
        ]

        const actual = calculateLayouts(tiles)

        expect(actual.xs?.map((l) => l.i)).toEqual(['1', '2', '3', '4', '5', '6'])
        const ys = actual.xs?.map((l) => l.y) || []
        expect(ys.every((y, i) => i === 0 || y > ys[i - 1])).toBe(true)
    })

    it.each([
        {
            name: 'uses default widget minH when catalog omits minH',
            widgetType: 'unknown_widget',
            expectedMinH: 4,
            expectedMinW: 3,
        },
        {
            name: 'uses catalog minW for error tracking list widgets',
            widgetType: 'error_tracking_list',
            expectedMinH: 3,
            expectedMinW: 3,
        },
        {
            name: 'uses catalog minW for session replay list widgets',
            widgetType: 'session_replay_list',
            expectedMinH: 3,
            expectedMinW: 3,
        },
    ])('$name', ({ widgetType, expectedMinH, expectedMinW }) => {
        const tiles: DashboardTile<QueryBasedInsightModel>[] = [
            {
                id: 1,
                widget: { widget_type: widgetType, config: {} },
                layouts: { sm: { i: '1', x: 0, y: 0, w: 6, h: 5 } },
            } as unknown as DashboardTile<QueryBasedInsightModel>,
        ]

        const result = calculateLayouts(tiles)

        expect(result.sm?.[0]?.minH).toBe(expectedMinH)
        expect(result.xs?.[0]?.minH).toBe(expectedMinH)
        expect(result.sm?.[0]?.minW).toBe(expectedMinW)
        expect(result.xs?.[0]?.minW).toBe(expectedMinW)
    })

    it('xs follows sm dirty-placement order when no tiles have stored sm layouts', () => {
        const tiles: DashboardTile<QueryBasedInsightModel>[] = [
            textTileWithLayout({} as Record<DashboardLayoutSize, TileLayout>, 1),
            textTileWithLayout({} as Record<DashboardLayoutSize, TileLayout>, 2),
            textTileWithLayout({} as Record<DashboardLayoutSize, TileLayout>, 3),
            textTileWithLayout({} as Record<DashboardLayoutSize, TileLayout>, 4),
        ]

        const actual = calculateLayouts(tiles)

        const smOrder = [...(actual.sm || [])].sort((a, b) => (a.y === b.y ? a.x - b.x : a.y - b.y)).map((l) => l.i)
        expect(actual.xs?.map((l) => l.i)).toEqual(smOrder)
    })
})

describe('calculateDuplicateLayout', () => {
    const smLayout = (i: string, x: number, y: number, w: number, h: number): LayoutItem => ({ i, x, y, w, h })

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
                tilesToUpdate: [{ id: 3, layouts: { sm: { x: 0, y: 10, w: 6, h: 5 } } }],
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
        const result = calculateDuplicateLayout(layouts as Partial<Record<DashboardLayoutSize, Layout>> | null, tileId)

        expect(result.duplicateLayouts).toEqual(expected.duplicateLayouts)
        expect(result.tilesToUpdate).toEqual(expected.tilesToUpdate)
    })

    it('only includes sm layout for duplicate (xs is derived)', () => {
        const layouts = {
            sm: [smLayout('1', 0, 0, 6, 5)],
            xs: [{ i: '1', x: 0, y: 0, w: 1, h: 5 } as LayoutItem],
        }

        const result = calculateDuplicateLayout(layouts, 1)

        expect(result.duplicateLayouts.sm).toEqual({ x: 6, y: 0, w: 6, h: 5 })
        expect((result.duplicateLayouts as any).xs).toBeUndefined()
    })
})

describe('calculateInsertionLayout', () => {
    const smLayout = (i: string, x: number, y: number, w: number, h: number): LayoutItem => ({ i, x, y, w, h })

    it.each([
        {
            name: 'inserting into the left column leaves the right column untouched',
            layout: [smLayout('1', 0, 0, 6, 5), smLayout('2', 6, 0, 6, 5)],
            newTileId: 9,
            targetX: 0,
            targetY: 0,
            w: 6,
            h: 2,
            expected: {
                newTileLayout: { sm: { x: 0, y: 0, w: 6, h: 2 } },
                tilesToUpdate: [{ id: 1, layouts: { sm: { x: 0, y: 2, w: 6, h: 5 } } }],
            },
        },
        {
            name: 'inserting into the right column pushes only the right column',
            layout: [smLayout('1', 0, 0, 6, 5), smLayout('2', 6, 0, 6, 5)],
            newTileId: 9,
            targetX: 6,
            targetY: 0,
            w: 6,
            h: 2,
            expected: {
                newTileLayout: { sm: { x: 6, y: 0, w: 6, h: 2 } },
                tilesToUpdate: [{ id: 2, layouts: { sm: { x: 6, y: 2, w: 6, h: 5 } } }],
            },
        },
        {
            name: 'a full-width insert pushes both columns down',
            layout: [smLayout('1', 0, 0, 6, 5), smLayout('2', 6, 0, 6, 5)],
            newTileId: 9,
            targetX: 0,
            targetY: 0,
            w: 12,
            h: 2,
            expected: {
                newTileLayout: { sm: { x: 0, y: 0, w: 12, h: 2 } },
                tilesToUpdate: [
                    { id: 1, layouts: { sm: { x: 0, y: 2, w: 6, h: 5 } } },
                    { id: 2, layouts: { sm: { x: 6, y: 2, w: 6, h: 5 } } },
                ],
            },
        },
        {
            name: 'insert in the middle only pushes same-column tiles at or below the row',
            layout: [smLayout('1', 0, 0, 6, 5), smLayout('2', 0, 5, 6, 5), smLayout('3', 0, 10, 6, 5)],
            newTileId: 9,
            targetX: 0,
            targetY: 5,
            w: 6,
            h: 3,
            expected: {
                newTileLayout: { sm: { x: 0, y: 5, w: 6, h: 3 } },
                tilesToUpdate: [
                    { id: 2, layouts: { sm: { x: 0, y: 8, w: 6, h: 5 } } },
                    { id: 3, layouts: { sm: { x: 0, y: 13, w: 6, h: 5 } } },
                ],
            },
        },
        {
            name: 'insert at the bottom shifts nothing',
            layout: [smLayout('1', 0, 0, 6, 5)],
            newTileId: 9,
            targetX: 0,
            targetY: 5,
            w: 2,
            h: 2,
            expected: {
                newTileLayout: { sm: { x: 0, y: 5, w: 2, h: 2 } },
                tilesToUpdate: [],
            },
        },
        {
            name: 'ignores the newly-added tile already present in the layout',
            layout: [smLayout('1', 0, 0, 6, 5), smLayout('9', 0, 5, 6, 5)],
            newTileId: 9,
            targetX: 0,
            targetY: 0,
            w: 6,
            h: 5,
            expected: {
                newTileLayout: { sm: { x: 0, y: 0, w: 6, h: 5 } },
                tilesToUpdate: [{ id: 1, layouts: { sm: { x: 0, y: 5, w: 6, h: 5 } } }],
            },
        },
    ])('$name', ({ layout, newTileId, targetX, targetY, w, h, expected }) => {
        const result = calculateInsertionLayout(layout, newTileId, targetY, targetX, w, h)

        expect(result.newTileLayout).toEqual(expected.newTileLayout)
        expect(result.tilesToUpdate).toEqual(expected.tilesToUpdate)
    })

    it('handles an undefined layout (first tile on an empty dashboard)', () => {
        const result = calculateInsertionLayout(undefined, 1, 0, 0, 6, 5)

        expect(result.newTileLayout).toEqual({ sm: { x: 0, y: 0, w: 6, h: 5 } })
        expect(result.tilesToUpdate).toEqual([])
    })
})
