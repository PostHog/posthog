import { onFilterChange } from 'scenes/insights/filters/BreakdownFilter/taxonomicBreakdownFilterUtils'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

const taxonomicGroupFor = (
    type: TaxonomicFilterGroupType,
    groupTypeIndex: number | undefined = undefined
): TaxonomicFilterGroup => ({
    type: type,
    groupTypeIndex: groupTypeIndex,
    name: 'unused in these tests',
    searchPlaceholder: 'unused in these tests',
    getName: () => 'unused in these tests',
    getValue: () => 'unused in these tests',
    getPopoverHeader: () => 'unused in these tests',
})

const setFilters = jest.fn()

const getPropertyDefinition = jest.fn()

describe('taxonomic breakdown filter utils', () => {
    it('sets breakdown for events', () => {
        const onChange = onFilterChange({
            breakdownParts: ['a', 'b'],
            setFilters,
            getPropertyDefinition,
        })
        const changedBreakdown = 'c'
        const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)
        onChange(changedBreakdown, group)
        expect(setFilters).toHaveBeenCalledWith(
            {
                breakdown_type: 'event',
                breakdown: 'c',
                breakdowns: undefined,
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
                breakdown_normalize_url: false,
            },
            true
        )
    })

    it('sets breakdown for cohorts', () => {
        const onChange = onFilterChange({
            breakdownParts: ['all', 1],
            setFilters,
            getPropertyDefinition,
        })
        const changedBreakdown = 2
        const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.CohortsWithAllUsers, undefined)
        onChange(changedBreakdown, group)
        expect(setFilters).toHaveBeenCalledWith(
            {
                breakdown_type: 'cohort',
                breakdown: ['all', 1, 2],
                breakdowns: undefined,
                breakdown_group_type_index: undefined,
                breakdown_normalize_url: false,
            },
            true
        )
    })

    it('sets breakdown for person properties', () => {
        const onChange = onFilterChange({
            breakdownParts: ['country'],
            setFilters,
            getPropertyDefinition,
        })
        const changedBreakdown = 'height'
        const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.PersonProperties, undefined)
        onChange(changedBreakdown, group)
        expect(setFilters).toHaveBeenCalledWith(
            {
                breakdown_type: 'person',
                breakdown: 'height',
                breakdowns: undefined,
                breakdown_group_type_index: undefined,
                breakdown_normalize_url: false,
            },
            true
        )
    })

    it('sets breakdowns for group properties', () => {
        const onChange = onFilterChange({
            breakdownParts: ['$lib'],
            setFilters,
            getPropertyDefinition,
        })
        const changedBreakdown = '$lib_version'
        const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.GroupsPrefix, 0)

        onChange(changedBreakdown, group)

        expect(setFilters).toHaveBeenCalledWith(
            {
                breakdown_type: 'group',
                breakdowns: undefined,
                breakdown: '$lib_version',
                breakdown_group_type_index: 0,
                breakdown_normalize_url: false,
            },
            true
        )
    })
})
