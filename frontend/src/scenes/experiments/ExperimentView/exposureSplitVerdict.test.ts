import { SampleRatioMismatch, SrmCause } from '~/queries/schema/schema-general'

import { getExposureSplitVerdict } from './exposureSplitVerdict'

function mismatch(diagnosis?: SampleRatioMismatch['diagnosis'], pValue = 1e-9): SampleRatioMismatch {
    return { expected: { control: 5000, test: 5000 }, p_value: pValue, diagnosis }
}

describe('getExposureSplitVerdict', () => {
    it('returns nothing when the backend ran no check', () => {
        expect(getExposureSplitVerdict(undefined)).toBeNull()
    })

    it('reports a matching split, so the collapsed header can say the split is expected', () => {
        const verdict = getExposureSplitVerdict(mismatch(undefined, 0.42))
        expect(verdict).toMatchObject({ isMismatch: false, label: 'Split matches rollout' })
    })

    it('names the skewed page and variant, which is what support writes out by hand', () => {
        const verdict = getExposureSplitVerdict(
            mismatch({
                cause: SrmCause.CaptureBySurface,
                surface_skew: {
                    surface: '/checkout',
                    variant: 'test',
                    variant_percentage: 99,
                    expected_percentage: 50,
                    exposures: 2000,
                },
            })
        )
        expect(verdict?.isMismatch).toBe(true)
        expect(verdict?.cause).toContain('/checkout')
        expect(verdict?.cause).toContain('test')
        expect(verdict?.nextStep).toContain('/checkout')
        expect(verdict?.suggestsExposureCriteriaFix).toBe(true)
    })

    it('explains a small sample without offering an exposure criteria edit that would not help', () => {
        const verdict = getExposureSplitVerdict(
            mismatch({ cause: SrmCause.LowSampleSize, smallest_expected_count: 250 })
        )
        expect(verdict?.cause).toContain('250')
        expect(verdict?.suggestsExposureCriteriaFix).toBe(false)
    })

    it.each([
        ['an unknown cause', { cause: SrmCause.Unknown }],
        ['no diagnosis at all, as on a response cached before this shipped', undefined],
        ['a surface cause with the surface missing', { cause: SrmCause.CaptureBySurface }],
    ])('still gives a next step with %s', (_name, diagnosis) => {
        const verdict = getExposureSplitVerdict(mismatch(diagnosis))
        expect(verdict?.isMismatch).toBe(true)
        expect(verdict?.nextStep).toBeTruthy()
    })
})
