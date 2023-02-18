import { actions, kea, path, reducers } from 'kea'
import { FilterType } from '~/types'

import type { dashboardTemplateVariablesLogicType } from './DashboardTemplateVariablesLogicType'

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    actions({
        setFilters: (filters: FilterType) => ({ filters }),
    }),
    reducers({
        filters: [
            undefined,
            {
                setFilters: (_, { filters }) => filters,
            },
        ],
    }),
])
