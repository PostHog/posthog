import { BreakdownType, FilterType } from '~/types'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterTypeToPropertyFilterType } from 'lib/components/PropertyFilters/utils'

interface FilterChange {
    multiPropertyBreakdownIsEnabled: string | boolean | undefined
    breakdownParts: (string | number)[]
    setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function onFilterChange({ multiPropertyBreakdownIsEnabled, breakdownParts, setFilters }: FilterChange) {
    return (changedBreakdown: TaxonomicFilterValue, groupType: TaxonomicFilterGroupType): void => {
        const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(groupType) as BreakdownType

        if (changedBreakdownType) {
            let newFilters: Partial<FilterType>
            if (multiPropertyBreakdownIsEnabled) {
                newFilters = {
                    breakdowns: [...breakdownParts, changedBreakdown]
                        .filter((b): b is string | number => !!b)
                        .map((b) => ({ property: b, type: changedBreakdownType })),
                    breakdown_type: changedBreakdownType,
                }
            } else {
                newFilters = {
                    breakdown:
                        groupType === TaxonomicFilterGroupType.CohortsWithAllUsers
                            ? [...breakdownParts, changedBreakdown].filter((b): b is string | number => !!b)
                            : changedBreakdown,
                    breakdown_type: changedBreakdownType,
                }
            }
            setFilters(newFilters)
        }
    }
}
