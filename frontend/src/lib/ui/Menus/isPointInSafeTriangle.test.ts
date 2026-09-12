import { isPointInSafeTriangle, Point, Rect } from './isPointInSafeTriangle'

describe('isPointInSafeTriangle', () => {
    const submenuOnTheRight: Rect = { left: 200, right: 400, top: 100, bottom: 300 }
    const leftOfSubmenu: Point = { x: 100, y: 110 }

    it.each<[string, Point, Point, Rect, boolean]>([
        ['a point on the diagonal towards the far corner', { x: 150, y: 200 }, leftOfSubmenu, submenuOnTheRight, true],
        ['a point straight ahead of the anchor', { x: 150, y: 110 }, leftOfSubmenu, submenuOnTheRight, true],
        ['a point past the diagonal to the far corner', { x: 150, y: 260 }, leftOfSubmenu, submenuOnTheRight, false],
        ['a point heading away from the submenu', { x: 150, y: 50 }, leftOfSubmenu, submenuOnTheRight, false],
        ['a point behind the anchor', { x: 50, y: 110 }, leftOfSubmenu, submenuOnTheRight, false],
        ['a point inside the submenu itself', { x: 300, y: 200 }, leftOfSubmenu, submenuOnTheRight, false],
        [
            'a point just past the corner, within the edge tolerance',
            { x: 199, y: 95 },
            { x: 100, y: 95 },
            submenuOnTheRight,
            true,
        ],
        [
            'a point heading to a submenu flipped to the left',
            { x: 450, y: 200 },
            { x: 500, y: 110 },
            submenuOnTheRight,
            true,
        ],
        [
            'a point heading to a submenu below the anchor',
            { x: 250, y: 250 },
            { x: 210, y: 50 },
            { left: 100, right: 400, top: 300, bottom: 500 },
            true,
        ],
        [
            'a point heading to a submenu above the anchor',
            { x: 250, y: 350 },
            { x: 210, y: 550 },
            { left: 100, right: 400, top: 100, bottom: 300 },
            true,
        ],
        [
            'any point when the anchor is inside the submenu',
            { x: 250, y: 250 },
            { x: 250, y: 200 },
            { left: 100, right: 400, top: 100, bottom: 300 },
            false,
        ],
    ])('%s', (_description, point, anchor, target, expected) => {
        expect(isPointInSafeTriangle(point, anchor, target)).toBe(expected)
    })
})
