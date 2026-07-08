import type { Series } from '../core/types'
import { applyComparisonDimming } from './comparison-dimming'

describe('applyComparisonDimming', () => {
    const A: Series = { key: 'a', label: 'A', data: [1, 2], color: '#112233' }
    const A_PREV: Series = { key: 'a-prev', label: 'A (prev)', data: [1, 2], color: '#112233' }
    const B: Series = { key: 'b', label: 'B', data: [3, 4], color: '#445566' }

    it.each([
        ['undefined', undefined],
        ['empty', {}],
    ] as const)('returns the same reference when comparisonOf is %s', (_label, comparisonOf) => {
        const series = [A, B]
        expect(applyComparisonDimming(series, comparisonOf)).toBe(series)
    })

    it('rewrites comparison series to a dimmed rgba colour, leaves primaries alone', () => {
        const result = applyComparisonDimming([A, A_PREV, B], { 'a-prev': 'a' })
        expect(result[0]).toBe(A)
        expect(result[2]).toBe(B)
        expect(result[1].color).toMatch(/^rgba\([^)]*,\s*0\.5\)$/)
    })

    it('leaves non-hex colours untouched (no double-wrapping)', () => {
        const rgbaSource: Series = { key: 'a-prev', label: '', data: [], color: 'rgba(0,0,0,1)' }
        const result = applyComparisonDimming([rgbaSource], { 'a-prev': 'a' })
        expect(result[0].color).toBe('rgba(0,0,0,1)')
    })
})
