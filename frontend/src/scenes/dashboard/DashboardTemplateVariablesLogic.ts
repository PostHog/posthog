import { actions, kea, path, reducers } from 'kea'
import { DashboardTemplateVariableType, FilterType, Optional } from '~/types'

import type { dashboardTemplateVariablesLogicType } from './DashboardTemplateVariablesLogicType'

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    actions({
        setVariables: (variables: DashboardTemplateVariableType[]) => ({ variables }),
        setVariable: (variable_name: string, filterGroup: Optional<FilterType, 'type'>) => ({
            variable_name,
            filterGroup,
        }),
    }),
    reducers({
        variables: [
            [] as DashboardTemplateVariableType[],
            {
                setVariables: (_, { variables }) => variables,
                setVariable: (
                    variables: DashboardTemplateVariableType[],
                    { variable_name, filterGroup }
                ): DashboardTemplateVariableType[] => {
                    // TODO: handle actions as well as events
                    return variables.map((v: DashboardTemplateVariableType) => {
                        if (v.name === variable_name && filterGroup?.events?.length && filterGroup.events[0]) {
                            v.default = filterGroup.events[0]
                        }
                        return v
                    })
                },
            },
        ],
    }),
])
