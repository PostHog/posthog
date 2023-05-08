import { BreakdownType, FilterType, PropertyDefinition, TrendsFilterType } from '~/types'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterTypeToPropertyFilterType } from 'lib/components/PropertyFilters/utils'

export const isURLNormalizeable = (propertyName: string): boolean => {
    return ['$current_url', '$pathname'].includes(propertyName)
}
interface FilterChange {
    breakdownParts: (string | number)[]
    setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    getPropertyDefinition: (propertyName: string | number) => PropertyDefinition | null
}

export function onFilterChange({ breakdownParts, setFilters, getPropertyDefinition }: FilterChange) {
    return (changedBreakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup): void => {
        const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type) as BreakdownType

        if (changedBreakdownType && changedBreakdown !== null) {
            const isHistogramable = !!getPropertyDefinition(changedBreakdown)?.is_numerical

            const newFilters: Partial<TrendsFilterType> = {
                breakdown_type: changedBreakdownType,
                breakdown_group_type_index: taxonomicGroup.groupTypeIndex,
                breakdown_histogram_bin_count: isHistogramable ? 10 : undefined,
                // if property definitions are not loaded when this runs then a normalizeable URL will not be normalized.
                // For now, it is safe to fall back to `changedBreakdown`
                breakdown_normalize_url: isURLNormalizeable(
                    getPropertyDefinition(changedBreakdown)?.name || (changedBreakdown as string)
                ),
            }

            newFilters.breakdown =
                taxonomicGroup.type === TaxonomicFilterGroupType.CohortsWithAllUsers
                    ? [...breakdownParts, changedBreakdown].filter((b): b is string | number => !!b)
                    : changedBreakdown

            setFilters(newFilters, true)
        }
    }
}
