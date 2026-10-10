import type { DashboardTile, DashboardWidgetModel } from '~/types'

import { DashboardGridCompaction, getDashboardGridCompactor } from './dashboardCustomization'
import { getGroupTitlesByTileId } from './dashboardTileGroups'

const tile = (id: number, group_key: string | null): DashboardTile =>
    ({ id, group_key, layouts: {}, color: null }) as DashboardTile

const widgetTile = (id: number, group_key: string): DashboardTile =>
    ({ ...tile(id, group_key), widget: {} as DashboardWidgetModel }) as DashboardTile

describe('getGroupTitlesByTileId', () => {
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
        {
            name: 'picks the top-left tile after the grid compacts the layout',
            tiles: [tile(1, 'plans'), tile(2, 'plans'), tile(3, null)],
            layout: [
                { i: '1', x: 0, y: 5, w: 6, h: 2 },
                { i: '2', x: 6, y: 4, w: 6, h: 2 },
                { i: '3', x: 6, y: 0, w: 6, h: 4 },
            ],
            groupTitles: { plans: 'Pricing plans' },
            widgetTilesShown: true,
            expected: { 1: 'Pricing plans' },
        },
    ])('$name', ({ tiles, layout, groupTitles, widgetTilesShown, expected }) => {
        expect(
            getGroupTitlesByTileId({
                tiles,
                smLayout: layout,
                groupTitles,
                compactor: getDashboardGridCompactor(DashboardGridCompaction.Vertical),
                widgetTilesShown,
            })
        ).toEqual(expected)
    })
})
