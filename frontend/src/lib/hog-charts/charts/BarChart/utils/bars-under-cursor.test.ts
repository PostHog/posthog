import type { BarRect } from '../../../core/canvas-renderer'
import { cursorOutsideBarFillExtent } from './bars-under-cursor'

const verticalBar: BarRect = { x: 100, y: 120, width: 50, height: 200, corners: {}, dataIndex: 0 }
const horizontalBar: BarRect = { x: 60, y: 100, width: 140, height: 40, corners: {}, dataIndex: 0 }

describe('cursorOutsideBarFillExtent', () => {
    it.each([
        { desc: 'above the fill', y: 80, expected: true },
        { desc: 'on the fill cap', y: 120, expected: false },
        { desc: 'inside the fill', y: 220, expected: false },
        { desc: 'below the fill', y: 360, expected: true },
    ])('vertical bar — cursor $desc is over the track: $expected', ({ y, expected }) => {
        expect(cursorOutsideBarFillExtent(verticalBar, { x: 110, y }, false)).toBe(expected)
    })

    it.each([
        { desc: 'left of the fill', x: 40, expected: true },
        { desc: 'inside the fill', x: 120, expected: false },
        { desc: 'right of the fill', x: 300, expected: true },
    ])('horizontal bar — cursor $desc is over the track: $expected', ({ x, expected }) => {
        expect(cursorOutsideBarFillExtent(horizontalBar, { x, y: 110 }, true)).toBe(expected)
    })
})
