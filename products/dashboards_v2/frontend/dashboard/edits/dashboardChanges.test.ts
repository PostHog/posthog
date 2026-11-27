import type { Dashboard, Tile } from '../document/dashboardTypes'
import { describeChanges } from './dashboardChanges'

const note = (id: string, title: string, x = 0): Tile => ({
    id,
    place: { x, y: 0, w: 6, h: 4 },
    panel: { type: 'markdown', title, config: { text: title } },
})

const section = (id: string, tiles: Tile[]): Tile => ({
    id,
    place: { x: 0, y: 4, w: 24, h: 6 },
    panel: { type: 'section', title: 'Errors', tiles },
})

const board = (tabs: Dashboard['tabs'], title = 'Board'): Dashboard => ({ version: 2, title, tabs })

const BASE = board([
    { id: 'one', title: 'One', tiles: [note('a', 'Signups'), section('s', [note('b', 'Failures')])] },
    { id: 'two', title: 'Two', tiles: [note('c', 'Revenue')] },
])

describe('describeChanges', () => {
    test.each<{ name: string; after: Dashboard; expected: string[] }>([
        { name: 'nothing changed', after: BASE, expected: [] },
        { name: 'reordered tabs', after: board([BASE.tabs[1], BASE.tabs[0]]), expected: ['Reordered the tabs'] },
        {
            name: 'a renamed dashboard and tab, an added tab, and a removed tab',
            after: board(
                [
                    { ...(BASE.tabs[0] as Dashboard['tabs'][number]), title: 'First' },
                    { id: 'three', title: 'Three', tiles: [] },
                ],
                'Renamed'
            ),
            expected: [
                'Renamed the dashboard to "Renamed"',
                'Renamed the "One" tab to "First"',
                'Added the "Three" tab',
                'Removed the "Two" tab',
                'Removed "Revenue"',
            ],
        },
        {
            name: 'a tile moved, one changed inside a section, and one added',
            after: board([
                {
                    id: 'one',
                    title: 'One',
                    tiles: [note('a', 'Signups', 6), section('s', [note('b', 'Errors by page')]), note('d', 'New')],
                },
                BASE.tabs[1],
            ]),
            expected: ['Moved or resized "Signups"', 'Changed "Errors by page"', 'Added "New"'],
        },
        {
            name: 'a tile moved out of a section into another tab',
            after: board([
                { id: 'one', title: 'One', tiles: [note('a', 'Signups'), section('s', [])] },
                { id: 'two', title: 'Two', tiles: [note('c', 'Revenue'), note('b', 'Failures')] },
            ]),
            expected: ['Moved "Failures" to another tab or section'],
        },
    ])('describes $name', ({ after, expected }) => {
        expect(describeChanges(BASE, after)).toEqual(expected)
    })
})
