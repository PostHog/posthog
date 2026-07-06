/**
 * Bridge hook that subscribes to every kea logic the legacy
 * `infiniteListLogic.rawLocalItems` selector reads via `group.logic` +
 * `group.value`. Returns a `getLocalOverride(groupType)` function the
 * orchestrator threads into per-tab `useGroupList(...)` calls so that
 * logic-backed groups (Actions, Cohorts, Experiments, Dashboards, Recent,
 * Pinned) populate their counts and item lists correctly.
 *
 * Without this bridge, headless `useGroupList` would only see `group.options`
 * + `optionsFromProp` and report `0` for every logic-backed tab.
 */
import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { taxonomicFilterPinnedPropertiesLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    ExcludedOperators,
    SelectingKeyOnly,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { filterRecentsForContext } from 'lib/components/TaxonomicFilter/utils/suggestedContextFilters'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'

import { actionsModel } from '~/models/actionsModel'
import { dashboardsModel } from '~/models/dashboardsModel'

import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

export type GetLocalOverride = (groupType: TaxonomicFilterGroupType) => TaxonomicDefinitionTypes[] | undefined

export function useTaxonomicLocalOverrides(context: {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    excludedOperators?: ExcludedOperators
    selectingKeyOnly?: SelectingKeyOnly
}): GetLocalOverride {
    const { taxonomicGroupTypes, excludedOperators, selectingKeyOnly } = context
    const { actionsSorted } = useValues(actionsModel)
    const { recentFilterItems } = useValues(recentTaxonomicFiltersLogic)
    const { pinnedFilterItems } = useValues(taxonomicFilterPinnedPropertiesLogic)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { experiments } = useValues(experimentsLogic)
    const { dataWarehouseTablesAndViews } = useValues(dataWarehouseSettingsSceneLogic)
    const { columnsJoinedToPersons } = useValues(joinsLogic)

    // Memoized so repeated calls return the same array reference — the result feeds
    // `useGroupList` memo deps and `useEffect` deps (e.g. the sole-substantive-group
    // recents promotion), where a fresh array per render means an infinite update loop.
    const contextFilteredRecentItems = useMemo(
        () => filterRecentsForContext(recentFilterItems, taxonomicGroupTypes, excludedOperators, selectingKeyOnly),
        [recentFilterItems, taxonomicGroupTypes, excludedOperators, selectingKeyOnly]
    )

    return useCallback(
        (groupType: TaxonomicFilterGroupType): TaxonomicDefinitionTypes[] | undefined => {
            switch (groupType) {
                case TaxonomicFilterGroupType.Actions:
                    return actionsSorted as unknown as TaxonomicDefinitionTypes[]
                case TaxonomicFilterGroupType.RecentFilters:
                    return contextFilteredRecentItems
                case TaxonomicFilterGroupType.PinnedFilters:
                    return pinnedFilterItems
                case TaxonomicFilterGroupType.Dashboards:
                    return nameSortedDashboards as unknown as TaxonomicDefinitionTypes[]
                case TaxonomicFilterGroupType.Experiments:
                    return experiments as unknown as TaxonomicDefinitionTypes[]
                case TaxonomicFilterGroupType.DataWarehouse:
                    return dataWarehouseTablesAndViews as unknown as TaxonomicDefinitionTypes[]
                case TaxonomicFilterGroupType.DataWarehousePersonProperties:
                    return columnsJoinedToPersons as unknown as TaxonomicDefinitionTypes[]
                default:
                    return undefined
            }
        },
        [
            actionsSorted,
            contextFilteredRecentItems,
            pinnedFilterItems,
            nameSortedDashboards,
            experiments,
            dataWarehouseTablesAndViews,
            columnsJoinedToPersons,
        ]
    )
}
