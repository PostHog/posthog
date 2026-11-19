import { applyEdit, dropIntoGrid, findTile, settleDashboard, stackTiles } from './dashboardEdits'
import type { Dashboard, Tile } from './dashboardTypes'

const text = (id: string, x: number, y: number, w: number, h: number): Tile => ({
    id,
    place: { x, y, w, h },
    widget: { type: 'markdown', text: id },
})
const section = (id: string, x: number, y: number, w: number, tiles: Tile[]): Tile => ({
    id,
    place: { x, y, w, h: 1 },
    widget: { type: 'section', title: id, tiles },
})
const dashboard = (first: Tile[], second: Tile[] = []): Dashboard =>
    settleDashboard({
        version: 2,
        title: 'Test',
        tabs: [
            { id: 'first', title: 'First', tiles: first },
            { id: 'second', title: 'Second', tiles: second },
        ],
    })
const places = (tiles: Tile[], grid: string): string[] =>
    tiles.flatMap((tile) => [
        `${tile.id}@${grid}: ${tile.place.x},${tile.place.y},${tile.place.w},${tile.place.h}`,
        ...(tile.widget.type === 'section' ? places(tile.widget.tiles, tile.id) : []),
    ])
const allPlaces = (board: Dashboard): string[] => board.tabs.flatMap((tab) => places(tab.tiles, tab.id))

describe('dashboardEdits', () => {
    const nested = dashboard(
        [section('outer', 0, 0, 24, [section('inner', 0, 0, 12, [text('a', 0, 0, 6, 4)])]), text('below', 0, 9, 6, 2)],
        [text('other', 0, 0, 6, 3)]
    )

    test.each([
        {
            name: 'a section shrinks to an empty one when its last tile leaves, and what was below it moves up',
            edit: { edit: 'moveTile' as const, id: 'a', grid: 'first', x: 12, y: 20 },
            expected: [
                'outer@first: 0,0,24,4',
                'inner@outer: 0,0,12,3',
                'below@first: 0,4,6,2',
                'a@first: 12,4,6,4',
                'other@second: 0,0,6,3',
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
                'outer@first: 0,0,24,6',
                'inner@outer: 0,0,12,5',
                'a@inner: 0,0,6,4',
                'other@second: 0,0,6,3',
                'below@second: 0,3,6,2',
            ],
        },
    ])('$name', ({ edit, expected }) => {
        expect(allPlaces(applyEdit(nested, edit))).toEqual(expected)
    })

    it('sets the parts of a tile inside a section and leaves its siblings alone', () => {
        const parts = { header: false, footer: false }
        const board = applyEdit(nested, { edit: 'setTileParts', id: 'a', parts })

        expect(findTile(board, 'a')?.widget).toMatchObject({ parts })
        expect(findTile(board, 'below')?.widget).not.toHaveProperty('parts')
    })

    it('previews a section moved into a narrower grid with the height and children it is saved with', () => {
        const board = dashboard([
            section('wide', 0, 0, 24, [text('left', 0, 0, 12, 4), text('right', 12, 0, 12, 4)]),
            section('half', 0, 6, 12, []),
        ])
        const wide = findTile(board, 'wide')!
        const preview = dropIntoGrid([], 12, wide, 0, 0)
        const saved = findTile(applyEdit(board, { edit: 'moveTile', id: 'wide', grid: 'half', x: 0, y: 0 }), 'wide')

        expect(preview.find((tile) => tile.id === 'wide')).toEqual(saved)
    })

    it('stacks tiles full width in reading order, with chart heights capped and sections restacked', () => {
        const chart = (id: string, x: number, y: number, w: number, h: number): Tile => ({
            id,
            place: { x, y, w, h },
            widget: { type: 'line' },
        })
        const tiles = [
            chart('tall', 12, 0, 12, 12),
            text('note', 0, 0, 12, 3),
            chart('short', 0, 3, 12, 2),
            section('group', 0, 12, 24, [text('right', 12, 0, 12, 2), text('left', 0, 0, 12, 4)]),
        ]

        expect(places(stackTiles(tiles, 24), 'tab')).toEqual([
            'note@tab: 0,0,24,3',
            'tall@tab: 0,3,24,8',
            'short@tab: 0,11,24,5',
            'group@tab: 0,16,24,7',
            'left@group: 0,0,24,4',
            'right@group: 0,4,24,2',
        ])
    })
})
