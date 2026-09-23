import { resizeBounds, snapZoneAt, tidyLayout } from './osWindowGeometry'

const DESKTOP = { width: 1000, height: 600 }

describe('osWindowGeometry', () => {
    test.each([
        ['one window fills the desktop', 1, [{ x: 8, y: 8, width: 984, height: 584 }]],
        [
            'three windows put two on top and stretch the third across the bottom',
            3,
            [
                { x: 8, y: 8, width: 488, height: 288 },
                { x: 504, y: 8, width: 488, height: 288 },
                { x: 8, y: 304, width: 984, height: 288 },
            ],
        ],
    ])('tidy up: %s', (_description, count, expected) => {
        expect(tidyLayout(count, DESKTOP)).toEqual(expected)
    })

    test.each([
        [{ x: 5, y: 300 }, 'left'],
        [{ x: 995, y: 300 }, 'right'],
        [{ x: 500, y: 2 }, 'maximize'],
        [{ x: 500, y: 300 }, null],
    ])('a drag that ends at %o snaps to %s', (pointer, expected) => {
        expect(snapZoneAt(pointer, DESKTOP)).toEqual(expected)
    })

    test.each([
        ['left', { x: -50, y: 0 }, { x: 50, y: 100, width: 550, height: 400 }],
        ['left', { x: 400, y: 0 }, { x: 240, y: 100, width: 360, height: 400 }],
        ['bottom-right', { x: 20, y: 30 }, { x: 100, y: 100, width: 520, height: 430 }],
    ] as const)('resizing from the %s edge by %o keeps the opposite edge in place', (edge, delta, expected) => {
        expect(resizeBounds({ x: 100, y: 100, width: 500, height: 400 }, edge, delta)).toEqual(expected)
    })
})
