import { isPointInSafeTriangle, Point, Rect } from './safeTriangle'

describe('safeTriangle', () => {
    // A submenu sitting to the right of its trigger, the way Base UI places one by default.
    const submenuOnTheRight: Rect = { left: 200, right: 400, top: 100, bottom: 300 }
    const anchorLeftOfSubmenu: Point = { x: 100, y: 110 }

    const cases: [string, Point, Point, Rect, boolean][] = [
        [
            'keeps a point on the diagonal to the far corner',
            { x: 150, y: 200 },
            anchorLeftOfSubmenu,
            submenuOnTheRight,
            true,
        ],
        [
            'keeps a point straight ahead of the anchor',
            { x: 150, y: 110 },
            anchorLeftOfSubmenu,
            submenuOnTheRight,
            true,
        ],
        [
            'drops a point past the diagonal to the far corner',
            { x: 150, y: 260 },
            anchorLeftOfSubmenu,
            submenuOnTheRight,
            false,
        ],
        [
            'drops a point heading away from the submenu',
            { x: 150, y: 50 },
            anchorLeftOfSubmenu,
            submenuOnTheRight,
            false,
        ],
        ['drops a point behind the anchor', { x: 50, y: 110 }, anchorLeftOfSubmenu, submenuOnTheRight, false],
        [
            'keeps a point heading to a submenu on the left',
            { x: 450, y: 200 },
            { x: 500, y: 110 },
            { left: 200, right: 400, top: 100, bottom: 300 },
            true,
        ],
        [
            'keeps a point heading to a submenu below',
            { x: 250, y: 250 },
            { x: 210, y: 50 },
            { left: 100, right: 400, top: 300, bottom: 500 },
            true,
        ],
        [
            'drops a point whose anchor faces no edge',
            { x: 250, y: 250 },
            { x: 250, y: 200 },
            { left: 100, right: 400, top: 100, bottom: 300 },
            false,
        ],
    ]

    it.each(cases)('%s', (_name, point, anchor, rect, expected) => {
        expect(isPointInSafeTriangle(point, anchor, rect)).toBe(expected)
    })
})
