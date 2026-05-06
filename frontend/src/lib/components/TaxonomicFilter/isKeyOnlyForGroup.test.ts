import { TaxonomicFilterGroupType, isKeyOnlyForGroup } from 'lib/components/TaxonomicFilter/types'

describe('isKeyOnlyForGroup', () => {
    it.each([
        { name: 'undefined prop -> false', prop: undefined, group: TaxonomicFilterGroupType.Cohorts, expected: false },
        {
            name: 'true prop -> true for any group',
            prop: true,
            group: TaxonomicFilterGroupType.Cohorts,
            expected: true,
        },
        {
            name: 'true prop -> true even for events',
            prop: true,
            group: TaxonomicFilterGroupType.EventProperties,
            expected: true,
        },
        {
            name: 'per-group dict matches the asked group',
            prop: { [TaxonomicFilterGroupType.Cohorts]: true },
            group: TaxonomicFilterGroupType.Cohorts,
            expected: true,
        },
        {
            name: 'per-group dict does not match a different group',
            prop: { [TaxonomicFilterGroupType.Cohorts]: true },
            group: TaxonomicFilterGroupType.EventProperties,
            expected: false,
        },
        {
            name: 'per-group dict with explicit false',
            prop: { [TaxonomicFilterGroupType.Cohorts]: false },
            group: TaxonomicFilterGroupType.Cohorts,
            expected: false,
        },
        {
            name: 'undefined group -> false',
            prop: { [TaxonomicFilterGroupType.Cohorts]: true },
            group: undefined,
            expected: false,
        },
    ])('$name', ({ prop, group, expected }) => {
        expect(isKeyOnlyForGroup(prop, group)).toBe(expected)
    })
})
