import { mixColors, resolveCssColor } from './color-utils'

describe('mixColors', () => {
    it.each([
        {
            name: 'midpoint is halfway between the two colors',
            from: '#000000',
            to: '#ffffff',
            t: 0.5,
            expected: 'rgb(128, 128, 128)',
        },
        { name: 't=0 returns the from color', from: '#000000', to: '#ffffff', t: 0, expected: 'rgb(0, 0, 0)' },
        { name: 't=1 returns the to color', from: '#000000', to: '#ffffff', t: 1, expected: 'rgb(255, 255, 255)' },
        { name: 't below 0 clamps to the from color', from: '#000000', to: '#ffffff', t: -1, expected: 'rgb(0, 0, 0)' },
        {
            name: 't above 1 clamps to the to color',
            from: '#000000',
            to: '#ffffff',
            t: 2,
            expected: 'rgb(255, 255, 255)',
        },
        {
            name: 'interpolates opacity',
            from: 'rgba(255, 0, 0, 0.2)',
            to: 'rgba(255, 0, 0, 0.8)',
            t: 0.5,
            expected: 'rgba(255, 0, 0, 0.5)',
        },
    ])('$name', ({ from, to, t, expected }) => {
        expect(mixColors(from, to, t)).toBe(expected)
    })

    it('returns the original string when a color cannot be parsed', () => {
        expect(mixColors('not-a-color', '#ffffff', 0.5)).toBe('not-a-color')
    })
})

describe('resolveCssColor', () => {
    // Canvas can't resolve `var()`; if this stops resolving a variable accent, the Heatmap ramp
    // (dimColor → d3 parse → fillStyle) gets an unparseable string and cells render blank.
    function rootWithVars(vars: Record<string, string>): HTMLElement {
        const el = document.createElement('div')
        for (const [name, value] of Object.entries(vars)) {
            el.style.setProperty(name, value)
        }
        document.body.appendChild(el)
        return el
    }

    afterEach(() => {
        document.body.replaceChildren()
    })

    it('passes a concrete color through unchanged', () => {
        expect(resolveCssColor('#1d4aff')).toBe('#1d4aff')
        expect(resolveCssColor('rgb(1, 2, 3)')).toBe('rgb(1, 2, 3)')
    })

    it('resolves a CSS variable to its computed value', () => {
        const root = rootWithVars({ '--data-color-1': '#abcdef' })
        expect(resolveCssColor('var(--data-color-1)', root)).toBe('#abcdef')
    })

    it('uses the fallback when the variable is undefined', () => {
        const root = rootWithVars({})
        expect(resolveCssColor('var(--missing, #123456)', root)).toBe('#123456')
    })

    it('returns the raw string when the variable is undefined and has no fallback', () => {
        const root = rootWithVars({})
        expect(resolveCssColor('var(--missing)', root)).toBe('var(--missing)')
    })
})
