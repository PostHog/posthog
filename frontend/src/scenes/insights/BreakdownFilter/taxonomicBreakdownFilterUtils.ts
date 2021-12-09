import { BreakdownType, FilterType } from '~/types'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterTypeToPropertyFilterType } from 'lib/components/PropertyFilters/utils'

interface FilterChange {
    useMultiBreakdown: string | boolean | undefined
    breakdownParts: (string | number)[]
    setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function onFilterChange({ useMultiBreakdown, breakdownParts, setFilters }: FilterChange) {
    return (changedBreakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup): void => {
        const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type) as BreakdownType

        if (changedBreakdownType) {
            const newFilters: Partial<FilterType> = {
                breakdown_type: changedBreakdownType,
                breakdown_group_type_index: taxonomicGroup.groupTypeIndex,
            }

            if (useMultiBreakdown) {
                newFilters.breakdowns = [...breakdownParts, changedBreakdown]
                    .filter((b): b is string | number => !!b)
                    .map((b) => ({ property: b, type: changedBreakdownType }))
            } else {
                newFilters.breakdown =
                    taxonomicGroup.type === TaxonomicFilterGroupType.CohortsWithAllUsers
                        ? [...breakdownParts, changedBreakdown].filter((b): b is string | number => !!b)
                        : changedBreakdown
            }

            setFilters(newFilters)
        }
    }
}
