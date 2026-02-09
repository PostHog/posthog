import { connect, kea, path, selectors } from 'kea'

import { SelectedQuickFilter, quickFiltersSectionLogic } from 'lib/components/QuickFilters'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType } from '~/types'

import type { dashboardQuickFiltersLogicType } from './dashboardQuickFiltersLogicType'

export const dashboardQuickFiltersLogic = kea<dashboardQuickFiltersLogicType>([
    path(['scenes', 'dashboard', 'dashboardQuickFiltersLogic']),

    connect(() => {
        const context = QuickFilterContext.Dashboards
        return {
            values: [quickFiltersSectionLogic({ context }), ['selectedQuickFilters']],
        }
    }),

    selectors({
        // Keyed by filter ID so dashboardLogic can scope to dashboard.quick_filter_ids
        quickFilterPropertyFiltersById: [
            (s) => [s.selectedQuickFilters],
            (selectedQuickFilters: Record<string, SelectedQuickFilter>): Record<string, AnyPropertyFilter> => {
                return Object.fromEntries(
                    Object.entries(selectedQuickFilters).map(([filterId, filter]) => [
                        filterId,
                        {
                            type: PropertyFilterType.Event,
                            key: filter.propertyName,
                            value: filter.value === null ? undefined : filter.value,
                            operator: filter.operator,
                        },
                    ])
                )
            },
        ],
    }),
])
