import { dropIntoGrid, stackTiles } from '../grid/gridTiles'
import { applyEdit, settleDashboard, withFolds, withoutTiles } from './dashboardEdits'
import { type Dashboard, type SizeOf, type Tile, type WidgetSize, gridTabs, isSection } from './dashboardTypes'
import { findTile } from './tileTree'

const SIZES: Record<string, WidgetSize> = {
    markdown: { w: 8, h: 8, minW: 3, minH: 4 },
    line: { w: 12, h: 16, minW: 4, minH: 8, stackedRows: { min: 10, max: 16 } },
}
const sizeOf: SizeOf = (widget) => SIZES[widget.type]

const text = (id: string, x: number, y: number, w: number, h: number): Tile => ({
    id,
    place: { x, y, w, h },
    widget: { type: 'markdown', config: { text: id } },
})
const section = (id: string, x: number, y: number, w: number, tiles: Tile[]): Tile => ({
    id,
    place: { x, y, w, h: 1 },
    widget: { type: 'section', title: id, tiles },
})
const dashboard = (first: Tile[], second: Tile[] = []): Dashboard =>
    settleDashboard(
        {
            version: 2,
            title: 'Test',
            tabs: [
                { id: 'first', title: 'First', tiles: first },
                { id: 'second', title: 'Second', tiles: second },
            ],
        },
        sizeOf
    )
const places = (tiles: Tile[], grid: string): string[] =>
    tiles.flatMap((tile) => [
        `${tile.id}@${grid}: ${tile.place.x},${tile.place.y},${tile.place.w},${tile.place.h}`,
        ...(isSection(tile) ? places(tile.widget.tiles, tile.id) : []),
    ])
const allPlaces = (board: Dashboard): string[] => gridTabs(board).flatMap((tab) => places(tab.tiles, tab.id))

describe('dashboardEdits', () => {
    const nested = dashboard(
        [section('outer', 0, 0, 24, [section('inner', 0, 0, 12, [text('a', 0, 0, 6, 8)])]), text('below', 0, 18, 6, 4)],
        [text('other', 0, 0, 6, 6)]
    )

    test.each([
        {
            name: 'a section shrinks to an empty one when its last tile leaves, and what was below it moves up',
            edit: { edit: 'moveTile' as const, id: 'a', grid: 'first', x: 12, y: 40 },
            expected: [
                'outer@first: 0,0,24,10',
                'inner@outer: 0,0,12,7',
                'below@first: 0,10,6,4',
                'a@first: 12,10,6,8',
                'other@second: 0,0,6,6',
            ],
        },
        {
            name: 'a section dropped into a section inside itself stays where it is',
            edit: { edit: 'moveTile' as const, id: 'outer', grid: 'inner', x: 0, y: 0 },
            expected: allPlaces(nested),
        },
        {
            name: 'a tile dropped on a tab goes to the bottom of that tab',
            edit: { edit: 'moveTile' as const, id: 'below', grid: 'second' },
            expected: [
                'outer@first: 0,0,24,14',
                'inner@outer: 0,0,12,11',
                'a@inner: 0,0,6,8',
                'other@second: 0,0,6,6',
                'below@second: 0,6,6,4',
            ],
        },
    ])('$name', ({ edit, expected }) => {
        expect(allPlaces(applyEdit(nested, edit, sizeOf))).toEqual(expected)
    })

    it('sets the parts of a tile inside a section and leaves its siblings alone', () => {
        const parts = { header: false, footer: false }
        const board = applyEdit(nested, { edit: 'setTileParts', id: 'a', parts }, sizeOf)

        expect(findTile(board, 'a')?.widget).toMatchObject({ parts })
        expect(findTile(board, 'below')?.widget).not.toHaveProperty('parts')
    })

    it('previews a section moved into a narrower grid with the height and children it is saved with', () => {
        const board = dashboard([
            section('wide', 0, 0, 24, [text('left', 0, 0, 12, 8), text('right', 12, 0, 12, 8)]),
            section('half', 0, 12, 12, []),
        ])
        const wide = findTile(board, 'wide')!
        const preview = dropIntoGrid([], 12, wide, 0, 0, sizeOf)
        const saved = findTile(
            applyEdit(board, { edit: 'moveTile', id: 'wide', grid: 'half', x: 0, y: 0 }, sizeOf),
            'wide'
        )

        expect(preview.find((tile) => tile.id === 'wide')).toEqual(saved)
    })

    it('stacks tiles full width in reading order, with chart heights capped and sections restacked', () => {
        const chart = (id: string, x: number, y: number, w: number, h: number): Tile => ({
            id,
            place: { x, y, w, h },
            widget: { type: 'line', config: {} },
        })
        const tiles = [
            chart('tall', 12, 0, 12, 24),
            text('note', 0, 0, 12, 6),
            chart('short', 0, 6, 12, 4),
            section('group', 0, 24, 24, [text('right', 12, 0, 12, 4), text('left', 0, 0, 12, 8)]),
        ]

        expect(places(stackTiles(tiles, 24, sizeOf), 'tab')).toEqual([
            'note@tab: 0,0,24,6',
            'tall@tab: 0,6,24,16',
            'short@tab: 0,22,24,10',
            'group@tab: 0,32,24,15',
            'left@group: 0,0,24,8',
            'right@group: 0,8,24,4',
        ])
    })

    it('closes a section for one viewer, moving the tiles below up, without changing the saved dashboard', () => {
        const board = dashboard([
            section('group', 0, 0, 24, [text('inside', 0, 0, 24, 8)]),
            text('below', 0, 12, 24, 4),
        ])
        const saved = JSON.stringify(board)

        expect(allPlaces(withFolds(board, { group: true }, sizeOf))).toEqual([
            'group@first: 0,0,24,3',
            'inside@group: 0,0,24,8',
            'below@first: 0,3,24,4',
        ])
        expect(JSON.stringify(board)).toEqual(saved)
    })

    it('hides tiles for one viewer, closing the gaps they leave, without changing the saved dashboard', () => {
        const board = dashboard([
            section('group', 0, 0, 24, [text('gone', 0, 0, 24, 8), text('kept', 0, 8, 24, 4)]),
            text('empty', 0, 14, 24, 6),
            text('below', 0, 20, 24, 4),
        ])
        const saved = JSON.stringify(board)

        expect(allPlaces(withoutTiles(board, ['gone', 'empty'], sizeOf))).toEqual([
            'group@first: 0,0,24,7',
            'kept@group: 0,0,24,4',
            'below@first: 0,7,24,4',
        ])
        expect(JSON.stringify(board)).toEqual(saved)
    })

    it.each([
        { name: 'keeps a section at the height it was resized to', h: 18, expected: 18, collapsed: false },
        { name: 'never lets a section be shorter than its tiles need', h: 4, expected: 11, collapsed: false },
        {
            name: 'keeps the height of a closed section that the person opened and resized',
            h: 18,
            expected: 18,
            collapsed: true,
        },
    ])('$name', ({ h, expected, collapsed }) => {
        const saved = section('group', 0, 0, 24, [text('inside', 0, 0, 24, 8)])
        const board = dashboard([
            { ...saved, widget: { ...saved.widget, collapsed } } as Tile,
            text('below', 0, 12, 24, 4),
        ])
        const view = (shown: Dashboard): Dashboard => withFolds(shown, { group: false }, sizeOf)
        const group = findTile(view(board), 'group')!
        const edit = {
            edit: 'placeTiles',
            grid: 'first',
            places: { group: { ...group.place, h } },
            resized: 'group',
        } as const

        const resized = applyEdit(board, edit, sizeOf, view)
        const later = applyEdit(resized, { edit: 'moveTile', id: 'below', grid: 'first', x: 0, y: 40 }, sizeOf, view)

        expect(findTile(view(later), 'group')!.place.h).toEqual(expected)
    })

    it('scales the tiles in a section made narrower, nested sections included, keeping each at its minimum width', () => {
        const board = dashboard([
            section('s', 0, 0, 24, [
                text('a', 0, 0, 12, 8),
                text('b', 12, 0, 6, 8),
                text('c', 18, 0, 6, 8),
                section('n', 0, 8, 24, [text('d', 0, 0, 12, 8)]),
            ]),
        ])
        const narrowed = applyEdit(
            board,
            { edit: 'placeTiles', grid: 'first', places: { s: { x: 0, y: 0, w: 8, h: 11 } }, resized: 's' },
            sizeOf
        )
        expect(places(gridTabs(narrowed)[0].tiles, 'first').slice(1)).toEqual([
            'a@s: 0,0,4,8',
            'b@s: 4,0,3,8',
            'c@s: 5,8,3,8',
            'n@s: 0,16,8,11',
            'd@n: 0,0,4,8',
        ])
    })

    it('auto-lays out a section in equal columns in reading order, giving spare columns to the left', () => {
        const board = dashboard([
            section('s', 0, 0, 10, [
                text('b', 5, 0, 5, 4),
                text('a', 0, 0, 5, 8),
                text('c', 0, 8, 10, 6),
                text('d', 0, 14, 4, 4),
            ]),
        ])
        const arranged = applyEdit(board, { edit: 'autoLayout', grid: 's', columns: 3 }, sizeOf)
        expect(places(gridTabs(arranged)[0].tiles, 'first').slice(1)).toEqual([
            'a@s: 0,0,4,8',
            'b@s: 4,0,3,4',
            'c@s: 7,0,3,6',
            'd@s: 0,8,4,4',
        ])
    })

    it('keeps a tile at its minimum width when auto layout gives it a narrower column', () => {
        const board = dashboard([
            section('s', 0, 0, 8, [text('a', 0, 0, 3, 4), text('b', 3, 0, 3, 4), text('c', 6, 0, 2, 4)]),
        ])
        const arranged = applyEdit(board, { edit: 'autoLayout', grid: 's', columns: 3 }, sizeOf)
        expect(places(gridTabs(arranged)[0].tiles, 'first').slice(1)).toEqual([
            'a@s: 0,0,3,4',
            'b@s: 3,0,3,4',
            'c@s: 5,4,3,4',
        ])
    })

    it('shows a tile on another tab, and a config change on either tile reaches both', () => {
        const board = dashboard([text('a', 0, 0, 8, 8)])
        const shared = applyEdit(board, { edit: 'addToGrid', id: 'a', grid: 'second' }, sizeOf)
        const copy = gridTabs(shared)[1].tiles[0]
        const edited = applyEdit(shared, { edit: 'setWidgetConfig', id: copy.id, config: { text: 'new' } }, sizeOf)
        expect([findTile(edited, 'a'), findTile(edited, copy.id)].map((tile) => tile?.widget)).toEqual([
            { type: 'markdown', config: { text: 'new' }, ref: 'widget1' },
            { type: 'markdown', config: { text: 'new' }, ref: 'widget1' },
        ])
    })

    it('keeps the last tab with tiles when only link tabs would be left', () => {
        const board: Dashboard = {
            ...dashboard([text('a', 0, 0, 8, 8)]),
            tabs: [
                { id: 'only', title: 'Only', tiles: [] },
                { id: 'docs', title: 'Docs', href: 'https://example.com' },
            ],
        }

        expect(applyEdit(board, { edit: 'removeTab', id: 'only' }, sizeOf).tabs.map((tab) => tab.id)).toEqual([
            'only',
            'docs',
        ])
        expect(applyEdit(board, { edit: 'removeTab', id: 'docs' }, sizeOf).tabs.map((tab) => tab.id)).toEqual(['only'])
    })

    it.each(['javascript:alert(1)', '//example.com/phish'])('refuses a link tab to %s', (href) => {
        const board = dashboard([text('a', 0, 0, 8, 8)])

        expect(applyEdit(board, { edit: 'addTab', title: 'Link', href }, sizeOf)).toEqual(board)
    })

    it('keeps a drag made in a folded view clear of the section in the saved layout', () => {
        const board = dashboard([
            section('group', 0, 0, 24, [text('inside', 0, 0, 24, 8)]),
            text('below', 0, 12, 12, 4),
            text('side', 12, 12, 12, 4),
        ])
        const viewed = withFolds(board, { group: true }, sizeOf)
        const grid = gridTabs(viewed)[0].tiles
        const dragged = Object.fromEntries(grid.map((tile) => [tile.id, tile.place]))
        dragged.side = { ...dragged.side, x: 0, y: 2 }
        dragged.below = { ...dragged.below, y: 6 }

        expect(allPlaces(applyEdit(board, { edit: 'placeTiles', grid: 'first', places: dragged }, sizeOf))).toEqual([
            'group@first: 0,0,24,11',
            'inside@group: 0,0,24,8',
            'below@first: 0,15,12,4',
            'side@first: 0,11,12,4',
        ])
    })

    it('drops a tile from another tab into the row the folded view showed, below the folded section', () => {
        const board = dashboard(
            [section('group', 0, 0, 24, [text('inside', 0, 0, 24, 8)]), text('below', 0, 12, 24, 4)],
            [text('other', 0, 0, 6, 6)]
        )
        const edit = { edit: 'moveTile' as const, id: 'other', grid: 'first', x: 0, y: 4 }

        expect(allPlaces(applyEdit(board, edit, sizeOf, (shown) => withFolds(shown, { group: true }, sizeOf)))).toEqual(
            ['group@first: 0,0,24,11', 'inside@group: 0,0,24,8', 'below@first: 5,11,19,4', 'other@first: 0,11,5,6']
        )
    })

    test.each<{ name: string; id: string; before: string | null; expected: string[] }>([
        {
            name: 'right, in front of a later tab',
            id: 'first',
            before: 'third',
            expected: ['second', 'first', 'third'],
        },
        { name: 'right, to the end', id: 'first', before: null, expected: ['second', 'third', 'first'] },
        { name: 'left, to the front', id: 'third', before: 'first', expected: ['third', 'first', 'second'] },
        { name: 'in front of itself', id: 'second', before: 'second', expected: ['first', 'second', 'third'] },
        {
            name: 'in front of the tab already after it',
            id: 'first',
            before: 'second',
            expected: ['first', 'second', 'third'],
        },
    ])('moves a tab $name and keeps its tiles', ({ id, before, expected }) => {
        const board = { ...nested, tabs: [...nested.tabs, { id: 'third', title: 'Third', tiles: [] }] }

        const moved = applyEdit(board, { edit: 'moveTab', id, before }, sizeOf)

        expect(moved.tabs.map((tab) => tab.id)).toEqual(expected)
        expect(allPlaces(moved).sort()).toEqual(allPlaces(board).sort())
    })
})
