import { actions, kea, path, props, propsChanged, reducers } from 'kea'
import { DashboardTemplateVariableType, FilterType, Optional } from '~/types'

import type { dashboardTemplateVariablesLogicType } from './dashboardTemplateVariablesLogicType'

export interface DashboardTemplateVariablesLogicProps {
    variables: DashboardTemplateVariableType[]
}

export const dashboardTemplateVariablesLogic = kea<dashboardTemplateVariablesLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateVariablesLogic']),
    props({ variables: [] } as DashboardTemplateVariablesLogicProps),
    actions({
        setVariables: (variables: DashboardTemplateVariableType[]) => ({ variables }),
        setVariable: (variableName: string, filterGroup: Optional<FilterType, 'type'>) => ({
            variable_name: variableName,
            filterGroup,
        }),
    }),
    reducers({
        variables: [
            [] as DashboardTemplateVariableType[],
            {
                setVariables: (_, { variables }) => variables,
                setVariable: (state, { variable_name: variableName, filterGroup }): DashboardTemplateVariableType[] => {
                    // TODO: handle actions as well as events
                    return state.map((v: DashboardTemplateVariableType) => {
                        if (v.name === variableName && filterGroup?.events?.length && filterGroup.events[0]) {
                            return { ...v, default: filterGroup.events[0] }
                        }
                        return v
                    })
                },
            },
        ],
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.variables !== oldProps.variables) {
            actions.setVariables(props.variables)
        }
    }),
])
