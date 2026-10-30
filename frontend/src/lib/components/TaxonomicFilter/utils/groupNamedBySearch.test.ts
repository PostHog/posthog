import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupNamedBySearch } from './groupNamedBySearch'

describe('groupNamedBySearch', () => {
    const propertyPicker = [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.EventFeatureFlags,
    ]
    const personPicker = [TaxonomicFilterGroupType.Persons, TaxonomicFilterGroupType.CohortsWithAllUsers]

    it.each([
        { searchQuery: 'person', offered: propertyPicker, expected: TaxonomicFilterGroupType.PersonProperties },
        { searchQuery: '  Users ', offered: propertyPicker, expected: TaxonomicFilterGroupType.PersonProperties },
        { searchQuery: 'EVENTS', offered: propertyPicker, expected: TaxonomicFilterGroupType.Events },
        { searchQuery: 'feature flags', offered: propertyPicker, expected: TaxonomicFilterGroupType.EventFeatureFlags },
        { searchQuery: 'persons', offered: personPicker, expected: TaxonomicFilterGroupType.Persons },
        { searchQuery: 'cohort', offered: personPicker, expected: TaxonomicFilterGroupType.CohortsWithAllUsers },
        {
            searchQuery: 'person',
            offered: [TaxonomicFilterGroupType.Persons, TaxonomicFilterGroupType.PersonProperties],
            expected: TaxonomicFilterGroupType.PersonProperties,
        },
        {
            searchQuery: 'cohort',
            offered: [TaxonomicFilterGroupType.CohortsWithAllUsers, TaxonomicFilterGroupType.Cohorts],
            expected: TaxonomicFilterGroupType.Cohorts,
        },
        {
            searchQuery: 'flags',
            offered: [TaxonomicFilterGroupType.FeatureFlags, TaxonomicFilterGroupType.EventFeatureFlags],
            expected: TaxonomicFilterGroupType.EventFeatureFlags,
        },
        {
            searchQuery: 'flag',
            offered: [TaxonomicFilterGroupType.FeatureFlags],
            expected: TaxonomicFilterGroupType.FeatureFlags,
        },
        { searchQuery: 'session', offered: propertyPicker, expected: null },
        { searchQuery: 'person_id', offered: propertyPicker, expected: null },
        { searchQuery: 'email', offered: propertyPicker, expected: null },
        { searchQuery: 'constructor', offered: propertyPicker, expected: null },
    ])('maps "$searchQuery" to $expected', ({ searchQuery, offered, expected }) => {
        expect(groupNamedBySearch(searchQuery, offered)).toEqual(expected)
    })
})
