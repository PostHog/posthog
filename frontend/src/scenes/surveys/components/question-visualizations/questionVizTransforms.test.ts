import { hexToRGBA } from 'lib/utils'

import { computeBarColors } from './questionVizTransforms'

const BLUE = '#1D4BFF'
const PINK = '#CD0F74'
const TEAL = '#43827E'

describe('computeBarColors', () => {
    const labels = ['a', 'b', 'c']
    const baseColors = [BLUE, PINK, TEAL]

    it('returns the base colors unchanged when nothing is highlighted', () => {
        expect(computeBarColors(baseColors, labels, null, false)).toEqual(baseColors)
    })

    it('keeps the highlighted bar at full color and dims the rest with the active alpha', () => {
        expect(computeBarColors(baseColors, labels, 'b', true)).toEqual([
            hexToRGBA(BLUE, 0.22),
            PINK,
            hexToRGBA(TEAL, 0.22),
        ])
    })

    it('uses the lighter armed alpha when no filter is active', () => {
        expect(computeBarColors(baseColors, labels, 'a', false)).toEqual([
            BLUE,
            hexToRGBA(PINK, 0.35),
            hexToRGBA(TEAL, 0.35),
        ])
    })

    it('dims every bar when the highlighted label matches none of them', () => {
        expect(computeBarColors(baseColors, labels, 'missing', true)).toEqual([
            hexToRGBA(BLUE, 0.22),
            hexToRGBA(PINK, 0.22),
            hexToRGBA(TEAL, 0.22),
        ])
    })
})
