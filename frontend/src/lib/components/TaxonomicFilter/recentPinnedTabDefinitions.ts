import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { taxonomicFilterPinnedPropertiesLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

export const RECENT_PINNED_TAB_DEFINITIONS = [
    {
        name: 'Recent',
        searchPlaceholder: 'recent',
        type: TaxonomicFilterGroupType.RecentFilters,
        isLocalOnly: true,
        isMetaGroup: true,
        logic: recentTaxonomicFiltersLogic,
        value: 'recentFilterItems',
        getName: (item: TaxonomicDefinitionTypes) => ('name' in item ? item.name : '') || '',
        getValue: (item: TaxonomicDefinitionTypes): TaxonomicFilterValue =>
            'name' in item ? (item.name ?? null) : null,
        getPopoverHeader: () => 'Recent',
    },
    {
        name: 'Pinned',
        searchPlaceholder: 'pinned',
        type: TaxonomicFilterGroupType.PinnedFilters,
        isLocalOnly: true,
        isMetaGroup: true,
        logic: taxonomicFilterPinnedPropertiesLogic,
        value: 'pinnedFilterItems',
        getName: (item: TaxonomicDefinitionTypes) => ('name' in item ? item.name : '') || '',
        getValue: (item: TaxonomicDefinitionTypes): TaxonomicFilterValue =>
            'name' in item ? (item.name ?? null) : null,
        getPopoverHeader: () => 'Pinned',
    },
] as const satisfies readonly TaxonomicFilterGroup[]
