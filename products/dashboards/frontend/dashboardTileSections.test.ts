import type { Layout } from 'react-grid-layout'

import type { DashboardTile } from '~/types'

import {
    getCollapsedTileGroupKeys,
    getDashboardSections,
    getSectionLayouts,
    hasSectionLayoutChanged,
    stackSectionLayouts,
} from './dashboardTileSections'
import type { DashboardTileGroupApi } from './generated/api.schemas'

const tile = (id: number, group_key: string | null = null): DashboardTile =>
    ({ id, group_key, layouts: {}, color: null }) as DashboardTile

const box = (id: number, x: number, y: number, w = 6, h = 2): Layout[number] => ({ i: String(id), x, y, w, h })

const sectionSummary = (
    tiles: DashboardTile[],
    layout: Layout | undefined,
    groups?: Record<string, DashboardTileGroupApi>
): string[] =>
    getDashboardSections({ tiles, layout, groups }).map((section) =>
        section.kind === 'group'
            ? `${section.groupKey}(${section.group.title ?? ''}): ${section.tiles.map((t) => t.id).join(',')}`
            : `tiles: ${section.tiles.map((t) => t.id).join(',')}`
    )

interface SectionsCase {
    name: string
    tiles: DashboardTile[]
    layout: Layout
    groups?: Record<string, DashboardTileGroupApi>
    expected: string[]
}

interface CollapsedCase {
    name: string
    tiles: DashboardTile[]
    groups: Record<string, DashboardTileGroupApi> | undefined
    choices: Record<string, boolean> | undefined
    expected: string[]
}

describe('dashboardTileSections', () => {
    it.each<SectionsCase>([
        {
            name: 'returns no sections for no tiles',
            tiles: [],
            layout: [],
            expected: [],
        },
        {
            name: 'keeps a dashboard without groups as one section in layout order',
            tiles: [tile(1), tile(2), tile(3)],
            layout: [box(1, 6, 2), box(2, 0, 0), box(3, 0, 2)],
            expected: ['tiles: 2,3,1'],
        },
        {
            name: 'puts each group where its top-left tile is and splits ungrouped tiles around it',
            tiles: [tile(1), tile(2, 'plans'), tile(3, 'plans'), tile(4)],
            layout: [box(1, 0, 0), box(2, 0, 2), box(3, 6, 4), box(4, 0, 6)],
            groups: { plans: { title: 'Pricing plans' } },
            expected: ['tiles: 1', 'plans(Pricing plans): 2,3', 'tiles: 4'],
        },
        {
            name: 'moves an ungrouped tile that sits beside a group to after the group',
            tiles: [tile(1, 'plans'), tile(2), tile(3, 'plans')],
            layout: [box(1, 0, 0), box(2, 6, 0), box(3, 0, 2)],
            expected: ['plans(): 1,3', 'tiles: 2'],
        },
        {
            name: 'keeps two groups apart even when their tiles share rows',
            tiles: [tile(1, 'plans'), tile(2, 'regions'), tile(3, 'plans'), tile(4, 'regions')],
            layout: [box(1, 0, 0), box(2, 6, 0), box(3, 0, 2), box(4, 6, 2)],
            expected: ['plans(): 1,3', 'regions(): 2,4'],
        },
        {
            name: 'puts tiles without a layout last',
            tiles: [tile(1), tile(2, 'plans'), tile(3)],
            layout: [box(2, 0, 0)],
            expected: ['plans(): 2', 'tiles: 1,3'],
        },
        {
            name: 'gives a group without settings no title',
            tiles: [tile(1, 'plans')],
            layout: [box(1, 0, 0)],
            groups: { regions: { title: 'Regions' } },
            expected: ['plans(): 1'],
        },
        ...['__proto__', 'constructor', 'toString'].map((groupKey) => ({
            name: `does not read settings for the inherited object key ${groupKey}`,
            tiles: [tile(1, groupKey)],
            layout: [box(1, 0, 0)],
            groups: { plans: { title: 'Pricing plans' } },
            expected: [`${groupKey}(): 1`],
        })),
    ])('getDashboardSections $name', ({ tiles, layout, groups, expected }) => {
        expect(sectionSummary(tiles, layout, groups)).toEqual(expected)
    })

    it('keeps section keys when tiles reorder inside their bands', () => {
        const tiles = [tile(1), tile(2), tile(3, 'plans'), tile(4), tile(5)]
        const sectionKeys = (layout: Layout): string[] =>
            getDashboardSections({ tiles, layout, groups: undefined }).map((section) => section.key)

        expect(sectionKeys([box(1, 0, 0), box(2, 6, 0), box(3, 0, 2), box(4, 0, 4), box(5, 6, 4)])).toEqual(
            sectionKeys([box(2, 0, 0), box(1, 6, 0), box(3, 0, 2), box(5, 0, 4), box(4, 6, 4)])
        )
    })

    it.each([
        {
            name: 'keeps only the section tiles and moves them to the top',
            layouts: { sm: [box(1, 0, 0), box(2, 0, 4), box(3, 6, 6)], xs: [box(2, 0, 9, 1)] },
            expected: { sm: [box(2, 0, 0), box(3, 6, 2)], xs: [box(2, 0, 0, 1)] },
        },
        {
            name: 'closes the single column gaps left by tiles of other bands',
            layouts: { xs: [box(3, 0, 10, 1, 5), box(1, 0, 5, 1, 5), box(2, 0, 0, 1, 5)] },
            expected: { xs: [box(2, 0, 0, 1, 5), box(3, 0, 5, 1, 5)] },
        },
    ])('getSectionLayouts $name', ({ layouts, expected }) => {
        expect(getSectionLayouts(layouts, [tile(2), tile(3)])).toEqual(expected)
    })

    it.each([
        { name: 'nothing', sections: [], expected: [] },
        {
            name: 'sections one under the other, each from its own top',
            sections: [[box(1, 0, 3, 6, 2), box(2, 6, 3, 6, 4)], [], [box(3, 0, 10, 12, 1)]],
            expected: [box(1, 0, 0, 6, 2), box(2, 6, 0, 6, 4), box(3, 0, 4, 12, 1)],
        },
    ])('stackSectionLayouts stacks $name', ({ sections, expected }) => {
        expect(stackSectionLayouts(sections)).toEqual(expected)
    })

    it.each([
        { name: 'the same tiles in another order', after: [box(2, 6, 0), box(1, 0, 0)], expected: false },
        { name: 'a tile moved sideways', after: [box(1, 6, 0), box(2, 0, 0)], expected: true },
        { name: 'a tile moved down', after: [box(1, 0, 2), box(2, 6, 0)], expected: true },
        { name: 'a tile resized', after: [box(1, 0, 0, 4), box(2, 6, 0)], expected: true },
        { name: 'a tile added', after: [box(1, 0, 0), box(2, 6, 0), box(3, 0, 2)], expected: true },
    ])('hasSectionLayoutChanged is $expected for $name', ({ after, expected }) => {
        expect(hasSectionLayoutChanged([box(1, 0, 0), box(2, 6, 0)], after)).toBe(expected)
    })

    it.each<CollapsedCase>([
        { name: 'nothing without groups', tiles: [tile(1)], groups: undefined, choices: undefined, expected: [] },
        {
            name: 'groups saved as collapsed',
            tiles: [tile(1, 'plans'), tile(2, 'regions'), tile(3, 'plans')],
            groups: { plans: { collapsed: true }, regions: { collapsed: false } },
            choices: undefined,
            expected: ['plans'],
        },
        {
            name: "the viewer's choice over the saved default",
            tiles: [tile(1, 'plans'), tile(2, 'regions')],
            groups: { plans: { collapsed: true } },
            choices: { plans: false, regions: true },
            expected: ['regions'],
        },
        {
            name: 'nothing for inherited object keys',
            tiles: [tile(1, 'constructor'), tile(2, 'toString')],
            groups: { plans: { collapsed: true } },
            choices: {},
            expected: [],
        },
    ])('getCollapsedTileGroupKeys finds $name', ({ tiles, groups, choices, expected }) => {
        expect(getCollapsedTileGroupKeys({ tiles, groups, choices })).toEqual(expected)
    })
})
