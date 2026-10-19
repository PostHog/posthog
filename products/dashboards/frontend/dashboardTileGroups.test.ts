import type { Layout } from 'react-grid-layout'

import { calculateLayouts } from 'scenes/dashboard/tileLayouts'

import type { DashboardLayoutSize, DashboardTile, DashboardWidgetModel, TileLayout } from '~/types'

import { DashboardGridCompaction, getDashboardGridCompactor } from './dashboardCustomization'
import { getGroupTitlesByTileId, hasTileDecorations } from './dashboardTileGroups'

const tile = (id: number, group_key: string | null): DashboardTile =>
    ({ id, group_key, layouts: {}, color: null }) as DashboardTile

const widgetTile = (id: number, group_key: string): DashboardTile =>
    ({ ...tile(id, group_key), widget: {} as DashboardWidgetModel }) as DashboardTile

const textTile = (id: number, group_key: string | null, sm: Omit<TileLayout, 'i'>): DashboardTile =>
    ({ ...tile(id, group_key), text: { body: 'text' }, layouts: { sm: { i: String(id), ...sm } } }) as DashboardTile

const tilesAboveAGap = (): DashboardTile[] => [
    textTile(1, 'plans', { x: 0, y: 5, w: 6, h: 2 }),
    textTile(2, 'plans', { x: 6, y: 4, w: 6, h: 2 }),
    textTile(3, null, { x: 6, y: 0, w: 6, h: 4 }),
]

interface GroupTitlesCase {
    name: string
    tiles: DashboardTile[]
    layout: Layout | undefined
    breakpoint?: DashboardLayoutSize
    groupTitles: Record<string, string> | undefined
    widgetTilesShown: boolean
    expected: Record<number, string>
}

describe('dashboardTileGroups', () => {
    it.each([
        {
            name: 'puts each title on the top-left tile of its group',
            tiles: [tile(1, 'plans'), tile(2, 'plans'), tile(3, 'regions'), tile(4, null)],
            layout: [
                { i: '1', x: 4, y: 0, w: 4, h: 2 },
                { i: '2', x: 0, y: 0, w: 4, h: 2 },
                { i: '3', x: 0, y: 2, w: 4, h: 2 },
                { i: '4', x: 0, y: 4, w: 4, h: 2 },
            ],
            groupTitles: { plans: 'Pricing plans', regions: 'Regions' },
            widgetTilesShown: true,
            expected: { 2: 'Pricing plans', 3: 'Regions' },
        },
        {
            name: 'skips groups without a title',
            tiles: [tile(1, 'plans'), tile(2, 'untitled')],
            layout: undefined,
            groupTitles: { plans: 'Pricing plans' } as Record<string, string>,
            widgetTilesShown: true,
            expected: { 1: 'Pricing plans' },
        },
        {
            name: 'draws nothing when the dashboard has no group titles',
            tiles: [tile(1, 'plans')],
            layout: undefined,
            groupTitles: undefined,
            widgetTilesShown: true,
            expected: {},
        },
        ...['__proto__', 'constructor', 'toString'].map((groupKey) => ({
            name: `ignores the inherited object key ${groupKey}`,
            tiles: [tile(1, groupKey)],
            layout: undefined,
            groupTitles: { plans: 'Pricing plans' } as Record<string, string>,
            widgetTilesShown: true,
            expected: {},
        })),
        ...[
            { widgetTilesShown: true, expected: { 1: 'Pricing plans' } },
            { widgetTilesShown: false, expected: { 2: 'Pricing plans' } },
        ].map(({ widgetTilesShown, expected }) => ({
            name: `puts the title on the first rendered tile when widget tiles shown is ${widgetTilesShown}`,
            tiles: [widgetTile(1, 'plans'), tile(2, 'plans')],
            layout: [
                { i: '1', x: 0, y: 0, w: 6, h: 2 },
                { i: '2', x: 6, y: 0, w: 6, h: 2 },
            ],
            groupTitles: { plans: 'Pricing plans' },
            widgetTilesShown,
            expected,
        })),
        ...[
            { breakpoint: 'sm' as DashboardLayoutSize, expected: { 1: 'Pricing plans' } },
            { breakpoint: 'xs' as DashboardLayoutSize, expected: { 2: 'Pricing plans' } },
        ].map(({ breakpoint, expected }) => {
            const tiles = tilesAboveAGap()
            return {
                name: `puts the title on the first tile the ${breakpoint} grid renders after compaction`,
                tiles,
                layout: calculateLayouts(tiles)[breakpoint],
                breakpoint,
                groupTitles: { plans: 'Pricing plans' },
                widgetTilesShown: true,
                expected,
            }
        }),
    ] as GroupTitlesCase[])(
        '$name',
        ({ tiles, layout, breakpoint = 'sm', groupTitles, widgetTilesShown, expected }) => {
            expect(
                getGroupTitlesByTileId({
                    tiles,
                    layout,
                    activeBreakpoint: breakpoint,
                    groupTitles,
                    compactor: getDashboardGridCompactor(DashboardGridCompaction.Vertical),
                    widgetTilesShown,
                })
            ).toEqual(expected)
        }
    )

    it.each([
        {
            name: 'a title on a rendered tile',
            tiles: [tile(1, 'plans')],
            groupTitlesByTileId: { 1: 'Plans' } as Record<number, string>,
            widgetTilesShown: true,
            expected: true,
        },
        {
            name: 'a badge on a rendered tile',
            tiles: [{ ...tile(1, null), badge: 'winner' } as DashboardTile],
            groupTitlesByTileId: {},
            widgetTilesShown: true,
            expected: true,
        },
        {
            name: 'a badge on a widget tile that is shown',
            tiles: [{ ...widgetTile(1, 'plans'), badge: 'winner' } as DashboardTile],
            groupTitlesByTileId: {},
            widgetTilesShown: true,
            expected: true,
        },
        {
            name: 'a badge on a widget tile that is hidden',
            tiles: [{ ...widgetTile(1, 'plans'), badge: 'winner' } as DashboardTile],
            groupTitlesByTileId: {},
            widgetTilesShown: false,
            expected: false,
        },
        {
            name: 'no title and no badge',
            tiles: [tile(1, null)],
            groupTitlesByTileId: {},
            widgetTilesShown: true,
            expected: false,
        },
    ])('hasTileDecorations is $expected for $name', ({ tiles, groupTitlesByTileId, widgetTilesShown, expected }) => {
        expect(hasTileDecorations({ tiles, groupTitlesByTileId, widgetTilesShown })).toBe(expected)
    })
})
