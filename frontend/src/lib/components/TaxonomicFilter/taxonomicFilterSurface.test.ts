import { legacyTaxonomicSurface } from './taxonomicFilterSurface'

describe('legacyTaxonomicSurface', () => {
    it.each([
        ['pill', 'legacy-pill'],
        ['control', 'legacy-control'],
        [undefined, 'legacy-control'],
        [true, 'legacy-control'],
        // `posthog.getFeatureFlag` returns `false` (not undefined) for a loaded flag with no variant.
        [false, 'legacy-control'],
        ['', 'legacy-control'],
    ])('maps category-dropdown variant %p to %p', (variant, expected) => {
        expect(legacyTaxonomicSurface(variant as string | boolean | undefined)).toBe(expected)
    })
})
