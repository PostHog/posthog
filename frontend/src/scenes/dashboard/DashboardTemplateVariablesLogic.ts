import { actions, kea, path, reducers } from 'kea'
import { AnyPropertyFilter } from '~/types'

import type { dashboardTemplateVariablesLogicType } from './DashboardTemplateVariablesLogicType'

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    actions({
        setProperties: (filters: AnyPropertyFilter[]) => ({ filters }),
    }),
    reducers({
        properties: [
            [] as AnyPropertyFilter[],
            {
                setProperties: (_, { filters }) => filters,
            },
        ],
    }),
])
