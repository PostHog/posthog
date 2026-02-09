import { actions, kea, key, path, props, reducers } from 'kea'

import type { dashboardFiltersLogicType } from './dashboardFiltersLogicType'

export interface DashboardFiltersLogicProps {
    dashboardId: number
}

export const dashboardFiltersLogic = kea<dashboardFiltersLogicType>([
    path(['scenes', 'dashboard', 'dashboardFiltersLogic']),
    props({} as DashboardFiltersLogicProps),
    key((props) => props.dashboardId),
    actions({
        setShowAdvancedFilters: (show: boolean) => ({ show }),
        toggleAdvancedFilters: true,
    }),
    reducers({
        showAdvancedFilters: [
            false,
            {
                setShowAdvancedFilters: (_, { show }) => show,
                toggleAdvancedFilters: (state) => !state,
            },
        ],
    }),
])
