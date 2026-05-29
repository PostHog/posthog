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

    it.each([
        { desc: 'inside band', x: 110, expected: true },
        { desc: 'outside band left', x: 80, expected: false },
        { desc: 'outside band right', x: 200, expected: false },
    ])('vertical bar — ignores y, checks band (x) axis only: $desc -> $expected', ({ x, expected }) => {
        expect(barContainsPointOnBandAxis(verticalBar, { x, y: -9999 }, false)).toBe(expected)
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

    it.each([
        { desc: 'inside the segment', x: 110, y: 220, expected: true },
        { desc: 'above the segment', x: 110, y: 80, expected: false },
        { desc: 'below the segment', x: 110, y: 360, expected: false },
        { desc: 'inside y but outside band', x: 80, y: 220, expected: false },
    ])('vertical bar — $desc -> $expected', ({ x, y, expected }) => {
        expect(barContainsPoint(verticalBar, { x, y })).toBe(expected)
    })

    // Half-open semantics on the trailing edge: matches d3 band-scale `[start, start + size)`,
    // so adjacent bars sharing a pixel boundary never both report a hit at that pixel.
    describe('boundary pixels (half-open trailing edge)', () => {
        it('vertical bar — leading edge (x=bar.x, y=bar.y) is inside', () => {
            expect(barContainsPoint(verticalBar, { x: verticalBar.x, y: verticalBar.y })).toBe(true)
        })

        it('vertical bar — trailing edge (x=bar.x+width, y=bar.y+height) is outside', () => {
            expect(
                barContainsPoint(verticalBar, {
                    x: verticalBar.x + verticalBar.width,
                    y: verticalBar.y + verticalBar.height,
                })
            ).toBe(false)
        })

        it('horizontal bar — leading edge (x=bar.x, y=bar.y) is inside', () => {
            expect(barContainsPoint(horizontalBar, { x: horizontalBar.x, y: horizontalBar.y })).toBe(true)
        })

        it('horizontal bar — trailing edge (x=bar.x+width, y=bar.y+height) is outside', () => {
            expect(
                barContainsPoint(horizontalBar, {
                    x: horizontalBar.x + horizontalBar.width,
                    y: horizontalBar.y + horizontalBar.height,
                })
            ).toBe(false)
        })
    })
})
