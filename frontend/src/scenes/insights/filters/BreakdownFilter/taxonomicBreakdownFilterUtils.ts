import { BreakdownType, FilterType, PropertyDefinition, TrendsFilterType } from '~/types'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterTypeToPropertyFilterType } from 'lib/components/PropertyFilters/utils'
import { isURLNormalizeable } from 'scenes/insights/filters/BreakdownFilter/index'

interface FilterChange {
    useMultiBreakdown: string | boolean | undefined
    breakdownParts: (string | number)[]
    setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    getPropertyDefinition: (propertyName: string | number) => PropertyDefinition | null
}

export function onFilterChange({ useMultiBreakdown, breakdownParts, setFilters, getPropertyDefinition }: FilterChange) {
    return (changedBreakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup): void => {
        const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type) as BreakdownType

        if (changedBreakdownType) {
            const isHistogramable = !useMultiBreakdown && !!getPropertyDefinition(changedBreakdown)?.is_numerical

            const newFilters: Partial<TrendsFilterType> = {
                breakdown_type: changedBreakdownType,
                breakdown_group_type_index: taxonomicGroup.groupTypeIndex,
                breakdown_histogram_bin_count: isHistogramable ? 10 : undefined,
                breakdown_normalize_url: isURLNormalizeable(getPropertyDefinition(changedBreakdown)?.name || ''),
            }

            if (useMultiBreakdown) {
                newFilters.breakdowns = [...breakdownParts, changedBreakdown]
                    .filter((b): b is string | number => !!b)
                    .map((b) => ({
                        property: b,
                        type: changedBreakdownType,
                        normalize_url: isURLNormalizeable(b.toString()),
                    }))
            } else {
                newFilters.breakdown =
                    taxonomicGroup.type === TaxonomicFilterGroupType.CohortsWithAllUsers
                        ? [...breakdownParts, changedBreakdown].filter((b): b is string | number => !!b)
                        : changedBreakdown
            }

            setFilters(newFilters, true)
        }
    }
}
