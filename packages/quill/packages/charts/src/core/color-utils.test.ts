import { mixColors } from './color-utils'

describe('mixColors', () => {
    it.each([
        { name: 'midpoint is halfway between the two colors', from: '#000000', to: '#ffffff', t: 0.5, expected: 'rgb(128, 128, 128)' },
        { name: 't=0 returns the from color', from: '#000000', to: '#ffffff', t: 0, expected: 'rgb(0, 0, 0)' },
        { name: 't=1 returns the to color', from: '#000000', to: '#ffffff', t: 1, expected: 'rgb(255, 255, 255)' },
        { name: 't below 0 clamps to the from color', from: '#000000', to: '#ffffff', t: -1, expected: 'rgb(0, 0, 0)' },
        { name: 't above 1 clamps to the to color', from: '#000000', to: '#ffffff', t: 2, expected: 'rgb(255, 255, 255)' },
        { name: 'interpolates opacity', from: 'rgba(255, 0, 0, 0.2)', to: 'rgba(255, 0, 0, 0.8)', t: 0.5, expected: 'rgba(255, 0, 0, 0.5)' },
    ])('$name', ({ from, to, t, expected }) => {
        expect(mixColors(from, to, t)).toBe(expected)
    })

    it('returns the original string when a color cannot be parsed', () => {
        expect(mixColors('not-a-color', '#ffffff', 0.5)).toBe('not-a-color')
    })
})
