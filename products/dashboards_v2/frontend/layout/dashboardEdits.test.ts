import { applyEdit, settleDashboard } from './dashboardEdits'
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
})
