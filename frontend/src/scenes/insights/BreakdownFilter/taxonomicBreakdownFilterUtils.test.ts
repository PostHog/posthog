import { onFilterChange } from 'scenes/insights/BreakdownFilter/taxonomicBreakdownFilterUtils'
import { FilterType } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

describe('taxonomic breakdown filter utils', () => {
    let setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    beforeEach(() => {
        setFilters = jest.fn()
    })

    describe('with multi property breakdown flag on', () => {
        it('sets breakdowns for events', () => {
            const onChange = onFilterChange({
                multiPropertyBreakdownIsEnabled: true,
                breakdownParts: ['a', 'b'],
                setFilters,
            })
            const changedBreakdown = 'c'
            const groupType: TaxonomicFilterGroupType = TaxonomicFilterGroupType.EventProperties

            onChange(changedBreakdown, groupType)

            expect(setFilters).toHaveBeenCalledWith({
                breakdown_type: 'event',
                breakdowns: [
                    { property: 'a', type: 'event' },
                    { property: 'b', type: 'event' },
                    { property: 'c', type: 'event' },
                ],
                breakdown: undefined,
                breakdown_group_type_index: undefined,
            })
        })

        it('sets breakdowns for cohorts', () => {
            const onChange = onFilterChange({
                multiPropertyBreakdownIsEnabled: true,
                breakdownParts: ['all', 1],
                setFilters,
            })
            const changedBreakdown = 2
            const groupType: TaxonomicFilterGroupType = TaxonomicFilterGroupType.CohortsWithAllUsers

            onChange(changedBreakdown, groupType)

            expect(setFilters).toHaveBeenCalledWith({
                breakdown_type: 'cohort',
                breakdowns: [
                    { property: 'all', type: 'cohort' },
                    { property: 1, type: 'cohort' },
                    { property: 2, type: 'cohort' },
                ],
                breakdown: undefined,
                breakdown_group_type_index: undefined,
            })
        })

        it('sets breakdowns for person properties', () => {
            const onChange = onFilterChange({
                multiPropertyBreakdownIsEnabled: true,
                breakdownParts: ['country'],
                setFilters,
            })
            const changedBreakdown = 'height'
            const groupType: TaxonomicFilterGroupType = TaxonomicFilterGroupType.PersonProperties

            onChange(changedBreakdown, groupType)

            expect(setFilters).toHaveBeenCalledWith({
                breakdown_type: 'person',
                breakdowns: [
                    { property: 'country', type: 'person' },
                    { property: 'height', type: 'person' },
                ],
                breakdown: undefined,
                breakdown_group_type_index: undefined,
            })
        })

        // multi property breakdown not implemented for groups
    })

    describe('with single property breakdown', () => {
        it('sets breakdown for events', () => {
            const onChange = onFilterChange({
                multiPropertyBreakdownIsEnabled: false,
                breakdownParts: ['a', 'b'],
                setFilters,
            })
            const changedBreakdown = 'c'
            const groupType: TaxonomicFilterGroupType = TaxonomicFilterGroupType.EventProperties
            onChange(changedBreakdown, groupType)
            expect(setFilters).toHaveBeenCalledWith({
                breakdown_type: 'event',
                breakdown: 'c',
                breakdowns: undefined,
                breakdown_group_type_index: undefined,
            })
        })

        it('sets breakdown for cohorts', () => {
            const onChange = onFilterChange({
                multiPropertyBreakdownIsEnabled: false,
                breakdownParts: ['all', 1],
                setFilters,
            })
            const changedBreakdown = 2
            const groupType: TaxonomicFilterGroupType = TaxonomicFilterGroupType.CohortsWithAllUsers
            onChange(changedBreakdown, groupType)
            expect(setFilters).toHaveBeenCalledWith({
                breakdown_type: 'cohort',
                breakdown: ['all', 1, 2],
                breakdowns: undefined,
                breakdown_group_type_index: undefined,
            })
        })

        it('sets breakdown for person properties', () => {
            const onChange = onFilterChange({
                multiPropertyBreakdownIsEnabled: false,
                breakdownParts: ['country'],
                setFilters,
            })
            const changedBreakdown = 'height'
            const groupType: TaxonomicFilterGroupType = TaxonomicFilterGroupType.PersonProperties
            onChange(changedBreakdown, groupType)
            expect(setFilters).toHaveBeenCalledWith({
                breakdown_type: 'person',
                breakdown: 'height',
                breakdowns: undefined,
                breakdown_group_type_index: undefined,
            })
        })

        it('sets breakdowns for group properties', () => {
            const onChange = onFilterChange({
                multiPropertyBreakdownIsEnabled: false,
                breakdownParts: ['$lib'],
                setFilters,
            })
            const changedBreakdown = '$lib_version'
            const groupType: TaxonomicFilterGroupType = TaxonomicFilterGroupType.GroupsPrefix

            onChange(changedBreakdown, groupType)

            expect(setFilters).toHaveBeenCalledWith({
                breakdown_type: 'group',
                breakdowns: undefined,
                breakdown: '$lib_version',
                breakdown_group_type_index: 0,
            })
        })
    })
})
