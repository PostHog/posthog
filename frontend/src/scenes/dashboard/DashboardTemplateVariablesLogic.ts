import { actions, kea, path, reducers } from 'kea'
import { DashboardTemplateVariableType, FilterType, Optional } from '~/types'

import type { dashboardTemplateVariablesLogicType } from './DashboardTemplateVariablesLogicType'

export function template(obj: any, variables: DashboardTemplateVariableType[]): any {
    if (typeof obj === 'string') {
        if (obj.startsWith('{') && obj.endsWith('}')) {
            const variableId = obj.substring(1, obj.length - 1)
            const variable = variables.find((variable) => variable.id === variableId)
            if (variable) {
                return variable.default
            }
            return obj
        }
    }
    if (Array.isArray(obj)) {
        return obj.map((item) => template(item, variables))
    }
    if (typeof obj === 'object') {
        const newObject: any = {}
        for (const [key, value] of Object.entries(obj)) {
            newObject[key] = template(value, variables)
        }
        return newObject
    }
    return obj
}

function makeTilesUsingVariables(tiles: any, variables: DashboardTemplateVariableType[]): any {
    return tiles.map((tile: any) => template(tile, variables))
}

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
                updateVariable: (variables: DashboardTemplateVariableType, { variable_name, filterGroup }) => {
                    console.log('reducer', variable_name, filterGroup)
                    return variables.map((v: DashboardTemplateVariableType) => {
                        if (v.name === variable_name) {
                            v.default = filterGroup.events[0]
                        }
                        return v
                    })
                },
            },
        ],
    }),
])
