import { type PlacedItem, placeTiles } from './placeTiles'

const item = (i: string, x: number, y: number, w: number, h: number, minW = 2): PlacedItem => ({ i, x, y, w, h, minW })
const places = (items: PlacedItem[]): Record<string, [number, number, number, number]> =>
    Object.fromEntries(items.map(({ i, x, y, w, h }) => [i, [x, y, w, h]]))

describe('placeTiles', () => {
    const fullRow = [item('a', 0, 0, 6, 3), item('b', 6, 0, 6, 3), item('c', 12, 0, 6, 3), item('d', 18, 0, 6, 3)]

    test.each([
        {
            name: 'closes the gap a removed tile left above',
            items: [item('a', 0, 4, 6, 3), item('b', 6, 0, 6, 3)],
            gesture: undefined,
            expected: { a: [0, 0, 6, 3], b: [6, 0, 6, 3] },
        },
        {
            name: 'slides a row apart when it has room for the dropped tile',
            items: [item('a', 0, 0, 6, 3), item('b', 6, 0, 6, 3), item('new', 4, 0, 6, 3)],
            gesture: {
                activeId: 'new',
                kind: 'drag' as const,
                baseline: [item('a', 0, 0, 6, 3), item('b', 6, 0, 6, 3)],
            },
            expected: { a: [0, 0, 6, 3], new: [6, 0, 6, 3], b: [12, 0, 6, 3] },
        },
        {
            name: 'narrows a full row instead of wrapping it',
            items: [...fullRow, item('new', 7, 0, 8, 3)],
            gesture: { activeId: 'new', kind: 'drag' as const, baseline: fullRow },
            expected: { a: [0, 0, 5, 3], b: [5, 0, 5, 3], new: [10, 0, 6, 3], c: [16, 0, 4, 3], d: [20, 0, 4, 3] },
        },
        {
            name: 'takes the place it was dropped on when that is part-way down a row that cannot get narrower',
            items: [item('wide', 0, 0, 24, 6, 24), item('new', 4, 2, 6, 3)],
            gesture: { activeId: 'new', kind: 'drag' as const, baseline: [item('wide', 0, 0, 24, 6, 24)] },
            expected: { new: [4, 0, 6, 3], wide: [0, 3, 24, 6] },
        },
        {
            name: 'goes under a row when dropped on its lower half',
            items: [item('wide', 0, 0, 24, 6, 24), item('new', 4, 4, 6, 3)],
            gesture: { activeId: 'new', kind: 'drag' as const, baseline: [item('wide', 0, 0, 24, 6, 24)] },
            expected: { wide: [0, 0, 24, 6], new: [4, 6, 6, 3] },
        },
        {
            name: 'keeps a resized tile in its row when it grows into a taller neighbour',
            items: [item('s', 0, 0, 8, 3), item('a', 0, 3, 10, 4), item('b', 8, 0, 16, 8)],
            gesture: {
                activeId: 'a',
                kind: 'resize' as const,
                baseline: [item('s', 0, 0, 8, 3), item('a', 0, 3, 8, 4), item('b', 8, 0, 16, 8)],
            },
            expected: { s: [0, 0, 8, 3], a: [0, 3, 10, 4], b: [8, 7, 16, 8] },
        },
        {
            name: 'gives the tile and the row their widths back once the tile leaves the row it narrowed',
            // The grid hands back its own last result, where the row is still narrow. The row must come back too.
            items: [
                item('a', 0, 0, 5, 3),
                item('b', 5, 0, 5, 3),
                item('c', 16, 0, 4, 3),
                item('d', 20, 0, 4, 3),
                item('new', 0, 9, 4, 3),
            ],
            gesture: { activeId: 'new', kind: 'drag' as const, baseline: [...fullRow, item('new', 0, 9, 8, 3)] },
            expected: { a: [0, 0, 6, 3], b: [6, 0, 6, 3], c: [12, 0, 6, 3], d: [18, 0, 6, 3], new: [0, 3, 8, 3] },
        },
        {
            name: 'pushes neighbours down on resize, without changing their widths',
            items: [item('a', 0, 0, 14, 3), item('b', 12, 0, 12, 3)],
            gesture: {
                activeId: 'a',
                kind: 'resize' as const,
                baseline: [item('a', 0, 0, 12, 3), item('b', 12, 0, 12, 3)],
            },
            expected: { a: [0, 0, 14, 3], b: [12, 3, 12, 3] },
        },
    ])('$name', ({ items, gesture, expected }) => {
        expect(places(placeTiles(items, 24, gesture))).toEqual(expected)
    })
})
