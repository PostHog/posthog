import { legacyTaxonomicSurface } from './taxonomicFilterSurface'

describe('legacyTaxonomicSurface', () => {
    it('reports the pill surface', () => {
        expect(legacyTaxonomicSurface()).toBe('legacy-pill')
    })
})
