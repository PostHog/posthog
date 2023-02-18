import { actions, kea, path, reducers } from 'kea'
import { FilterType } from '~/types'

import type { dashboardTemplateVariablesLogicType } from './DashboardTemplateVariablesLogicType'

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    actions({
        setFilterGroups: (newFilterGroups: Record<string, FilterType>) => ({ newFilterGroups }),
    }),
    reducers({
        filterGroups: [
            {},
            {
                setFilterGroups: (filterGroups, { newFilterGroups }) => ({ ...filterGroups, ...newFilterGroups }),
            },
        ],
    }),
])
