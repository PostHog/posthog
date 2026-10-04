import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from './helpers'

describe('getCoreFilterDefinition', () => {
    test.each([
        ['an object with a null prototype', Object.create(null)],
        ['an object whose toString is not a function', { toString: 'nope' }],
    ])('returns null for %s', (_, value) => {
        expect(getCoreFilterDefinition(value, TaxonomicFilterGroupType.EventProperties)).toBeNull()
    })

    it('still resolves a known string key', () => {
        expect(getCoreFilterDefinition('$browser', TaxonomicFilterGroupType.EventProperties)?.label).toBeTruthy()
    })
})
