import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { DEFAULT_TAXONOMIC_GROUP_TYPES, propertyFilterGroupTypes } from './TaxonomicPropertyFilter'

describe('propertyFilterGroupTypes', () => {
    it.each([
        {
            name: 'leads with the All tab ahead of the defaults',
            requested: undefined,
            expected: [TaxonomicFilterGroupType.SuggestedFilters, ...DEFAULT_TAXONOMIC_GROUP_TYPES],
        },
        {
            name: 'drops the pageview URL groups, because a Current URL filter covers them',
            requested: [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PageviewUrls,
                TaxonomicFilterGroupType.PageviewEvents,
                TaxonomicFilterGroupType.Screens,
            ],
            expected: [
                TaxonomicFilterGroupType.SuggestedFilters,
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.Screens,
            ],
        },
    ])('$name', ({ requested, expected }) => {
        expect(propertyFilterGroupTypes(requested)).toEqual(expected)
    })
})
