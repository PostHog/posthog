import type { BarRect } from '../../../core/canvas-renderer'
import { barContainsPoint, barContainsPointOnBandAxis, cursorOutsideBarFillExtent } from './bars-under-cursor'

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

describe('barContainsPointOnBandAxis', () => {
    it.each([
        { desc: 'inside band', y: 110, expected: true },
        { desc: 'outside band above', y: 80, expected: false },
        { desc: 'outside band below', y: 160, expected: false },
    ])('horizontal bar — ignores x, checks band (y) axis only: $desc -> $expected', ({ y, expected }) => {
        expect(barContainsPointOnBandAxis(horizontalBar, { x: -9999, y }, true)).toBe(expected)
    })
})

describe('barContainsPoint', () => {
    it.each([
        { desc: 'inside the segment', x: 120, y: 110, expected: true },
        { desc: 'left of the segment', x: 40, y: 110, expected: false },
        { desc: 'right of the segment', x: 300, y: 110, expected: false },
        { desc: 'inside x but outside band', x: 120, y: 80, expected: false },
    ])('horizontal bar — $desc -> $expected', ({ x, y, expected }) => {
        expect(barContainsPoint(horizontalBar, { x, y })).toBe(expected)
    })
})
