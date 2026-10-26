import type { Layout } from 'react-grid-layout'

import { pluralize } from 'lib/utils/strings'

import type { DashboardTile } from '~/types'

import { DashboardGridCompaction, getDashboardGridCompactor } from './dashboardCustomization'
import {
    getCollapsedTileGroupKeys,
    getDashboardSections,
    getLayoutAfterSectionChange,
    getLayoutAfterTileMove,
    getSectionLayouts,
    getTileGroupMoveOptions,
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

interface TileMoveCase {
    name: string
    tiles: DashboardTile[]
    targetKey: string | null
    cell: { x: number; y: number } | null
    expectedSections: string[]
    expectedTile?: Partial<Layout[number]>
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
        {
            name: 'does not read settings for an inherited object key',
            tiles: [tile(1, '__proto__')],
            layout: [box(1, 0, 0)],
            groups: { plans: { title: 'Pricing plans' } },
            expected: ['__proto__(): 1'],
        },
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
            name: 'keeps only the section tiles and closes the gaps that other bands leave',
            compaction: DashboardGridCompaction.Vertical,
            layouts: { sm: [box(1, 0, 0), box(2, 0, 4), box(3, 6, 6)], xs: [box(2, 0, 9, 1)] },
            expected: { sm: [box(2, 0, 0), box(3, 6, 0)], xs: [box(2, 0, 0, 1)] },
        },
        {
            name: 'keeps free-form placement and moves the section to the top',
            compaction: DashboardGridCompaction.Stable,
            layouts: { sm: [box(1, 0, 0), box(2, 0, 4), box(3, 6, 6)] },
            expected: { sm: [box(2, 0, 0), box(3, 6, 2)] },
        },
        {
            name: 'closes the single column gaps left by tiles of other bands',
            compaction: DashboardGridCompaction.Stable,
            layouts: { xs: [box(3, 0, 10, 1, 5), box(1, 0, 5, 1, 5), box(2, 0, 0, 1, 5)] },
            expected: { xs: [box(2, 0, 0, 1, 5), box(3, 0, 5, 1, 5)] },
        },
    ])('getSectionLayouts $name', ({ compaction, layouts, expected }) => {
        const sectionLayouts = getSectionLayouts(layouts, [tile(2), tile(3)], getDashboardGridCompactor(compaction))
        expect(sectionLayouts).toMatchObject(expected)
    })

    it('stackSectionLayouts stacks sections one under the other, each from its own top', () => {
        expect(stackSectionLayouts([[box(1, 0, 3, 6, 2), box(2, 6, 3, 6, 4)], [], [box(3, 0, 10, 12, 1)]])).toEqual([
            box(1, 0, 0, 6, 2),
            box(2, 6, 0, 6, 4),
            box(3, 0, 4, 12, 1),
        ])
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

    it.each([
        {
            name: 'nothing when the band reports its tiles in another order',
            reported: [box(2, 6, 0), box(1, 0, 0)],
            expected: null,
        },
        {
            name: 'nothing when no band holds the reported tiles',
            reported: [box(9, 0, 0)],
            expected: null,
        },
        {
            name: 'the moved band with the bands below it stacked under it',
            reported: [box(1, 0, 0), box(2, 0, 2)],
            expected: [box(1, 0, 0), box(2, 0, 2), box(3, 0, 4, 12)],
        },
        {
            name: 'a later band moved with the bands above it kept',
            reported: [box(3, 0, 0, 4)],
            expected: [box(1, 0, 0), box(2, 6, 0), box(3, 0, 2, 4)],
        },
    ])('getLayoutAfterSectionChange gives $name', ({ reported, expected }) => {
        const sectionLayouts = [[box(1, 0, 0), box(2, 6, 0)], [box(3, 0, 0, 12)]]
        expect(getLayoutAfterSectionChange(sectionLayouts, reported)).toEqual(expected)
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
    ])('getCollapsedTileGroupKeys finds $name', ({ tiles, groups, choices, expected }) => {
        expect(getCollapsedTileGroupKeys({ tiles, groups, choices })).toEqual(expected)
    })

    it.each<TileMoveCase>([
        {
            name: 'into a closed group goes below its tiles',
            tiles: [tile(1, 'plans'), tile(2, 'ops'), tile(3)],
            targetKey: 'group-ops',
            cell: null,
            expectedSections: ['ops(): 2,1', 'tiles: 3'],
        },
        {
            name: 'out of its group joins the last band when that band has no group',
            tiles: [tile(1, 'plans'), tile(2, 'ops'), tile(3)],
            targetKey: null,
            cell: null,
            expectedSections: ['ops(): 2', 'tiles: 3,1'],
        },
        {
            name: 'out of its group starts a band after the last group',
            tiles: [tile(1, 'plans'), tile(2, 'ops'), tile(3, 'ops')],
            targetKey: null,
            cell: null,
            expectedSections: ['ops(): 2,3', 'tiles: 1'],
        },
        {
            name: 'into another band lands at the drop cell',
            tiles: [tile(1, 'plans'), tile(2, 'ops'), tile(3)],
            targetKey: 'group-ops',
            cell: { x: 6, y: 0 },
            expectedSections: ['ops(): 2,1', 'tiles: 3'],
            expectedTile: { x: 6, y: 0 },
        },
    ])('getLayoutAfterTileMove: a tile moved $name', ({ tiles, targetKey, cell, expectedSections, expectedTile }) => {
        const layout = [box(1, 0, 0), box(2, 0, 2), box(3, 0, 4)]
        const sections = getDashboardSections({ tiles, layout, groups: undefined })
        const compactor = getDashboardGridCompactor(DashboardGridCompaction.Vertical)

        const moved = getLayoutAfterTileMove({
            layout,
            sections,
            sectionLayouts: sections.map((section) => getSectionLayouts({ sm: layout }, section.tiles, compactor).sm!),
            tileId: 1,
            target: sections.find((section) => section.key === targetKey) ?? null,
            cell,
            compactor,
        })
        const targetSection = sections.find((section) => section.key === targetKey)
        const movedTiles = tiles.map((t) =>
            t.id === 1 ? { ...t, group_key: targetSection?.kind === 'group' ? targetSection.groupKey : null } : t
        )

        expect(sectionSummary(movedTiles, moved)).toEqual(expectedSections)
        if (expectedTile) {
            expect(moved.find((item) => item.i === '1')).toMatchObject(expectedTile)
        }
    })

    it('getTileGroupMoveOptions offers the other groups by their band labels, and taking a grouped tile out', () => {
        const sections = getDashboardSections({
            tiles: [tile(1, 'plans'), tile(2, 'ops'), tile(3, 'ops'), tile(4)],
            layout: [box(1, 0, 0), box(2, 0, 2), box(3, 0, 4), box(4, 0, 6)],
            groups: { plans: { title: 'Pricing plans' } },
        })
        const plans = { sectionKey: 'group-plans', label: 'Pricing plans' }
        const ops = { sectionKey: 'group-ops', label: pluralize(2, 'tile') }

        expect(getTileGroupMoveOptions(sections)).toEqual({
            1: { targets: [ops], canTakeOut: true },
            2: { targets: [plans], canTakeOut: true },
            3: { targets: [plans], canTakeOut: true },
            4: { targets: [plans, ops], canTakeOut: false },
        })
    })
})
