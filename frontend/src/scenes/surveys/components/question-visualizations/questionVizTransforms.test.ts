import { computeBarColors } from './questionVizTransforms'

const BLUE = '#1D4BFF'
const PINK = '#CD0F74'
const TEAL = '#43827E'

function mixed(hex: string, keep: number, towards: number): string {
    const r = parseInt(hex.slice(1, 3), 16)
    const g = parseInt(hex.slice(3, 5), 16)
    const b = parseInt(hex.slice(5, 7), 16)
    const mix = (channel: number): number => Math.round(channel * keep + towards * (1 - keep))
    return `rgb(${mix(r)},${mix(g)},${mix(b)})`
}

describe('computeBarColors', () => {
    const labels = ['a', 'b', 'c']
    const baseColors = [BLUE, PINK, TEAL]

    it('returns the base colors unchanged when nothing is highlighted', () => {
        expect(computeBarColors(baseColors, labels, null, false, false)).toEqual(baseColors)
    })

    it('keeps the highlighted bar at full color and dims the rest with the active strength', () => {
        expect(computeBarColors(baseColors, labels, 'b', true, false)).toEqual([
            mixed(BLUE, 0.4, 255),
            PINK,
            mixed(TEAL, 0.4, 255),
        ])
    })

    it('uses the lighter armed strength when no filter is active', () => {
        expect(computeBarColors(baseColors, labels, 'a', false, false)).toEqual([
            BLUE,
            mixed(PINK, 0.55, 255),
            mixed(TEAL, 0.55, 255),
        ])
    })

    it('dims toward black in dark mode so dimmed bars stay opaque over the bar track', () => {
        expect(computeBarColors(baseColors, labels, 'b', true, true)).toEqual([
            mixed(BLUE, 0.4, 0),
            PINK,
            mixed(TEAL, 0.4, 0),
        ])
    })

    it('dims every bar when the highlighted label matches none of them', () => {
        expect(computeBarColors(baseColors, labels, 'missing', true, false)).toEqual([
            mixed(BLUE, 0.4, 255),
            mixed(PINK, 0.4, 255),
            mixed(TEAL, 0.4, 255),
        ])
    })
})
