import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupNamedBySearch } from './groupNamedBySearch'

describe('groupNamedBySearch', () => {
    const offered = [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.Cohorts,
    ]

    it.each([
        { searchQuery: 'person', expected: TaxonomicFilterGroupType.PersonProperties },
        { searchQuery: '  Users ', expected: TaxonomicFilterGroupType.PersonProperties },
        { searchQuery: 'EVENTS', expected: TaxonomicFilterGroupType.Events },
        { searchQuery: 'cohort', expected: TaxonomicFilterGroupType.Cohorts },
        { searchQuery: 'session', expected: null },
        { searchQuery: 'person_id', expected: null },
        { searchQuery: 'email', expected: null },
    ])('maps "$searchQuery" to $expected', ({ searchQuery, expected }) => {
        expect(groupNamedBySearch(searchQuery, offered)).toEqual(expected)
    })
})
