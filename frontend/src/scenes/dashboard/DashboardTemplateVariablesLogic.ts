import { actions, kea, path, reducers } from 'kea'
import { DashboardTemplateVariableType, FilterType, Optional } from '~/types'

import type { dashboardTemplateVariablesLogicType } from './DashboardTemplateVariablesLogicType'

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    actions({
        setVariables: (variables: DashboardTemplateVariableType[]) => ({ variables }),
        updateVariable: (variable_name: string, filterGroup: Optional<FilterType, 'type'>) => ({
            variable_name,
            filterGroup,
        }),
    }),
    reducers({
        variables: [
            [] as DashboardTemplateVariableType[],
            {
                setVariables: (_, { variables }) => variables,
                updateVariable: (
                    variables: DashboardTemplateVariableType[],
                    { variable_name, filterGroup }
                ): DashboardTemplateVariableType[] => {
                    // TODO: handle actions too
                    console.log('reducer', variable_name, filterGroup)
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
