import { kea, key, path, props, selectors } from 'kea'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { taxonomicFilterPinnedPropertiesLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import type { recentPinnedTaxonomicGroupsLogicType } from './recentPinnedTaxonomicGroupsLogicType'

export const recentPinnedTaxonomicGroupsLogic = kea<recentPinnedTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'recentPinnedTaxonomicGroupsLogic', key]),

    selectors({
        recentPinnedTaxonomicGroups: [
            () => [],
            (): TaxonomicFilterGroup[] => [
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
                } as TaxonomicFilterGroup,
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
                } as TaxonomicFilterGroup,
            ],
        ],
    }),
])
