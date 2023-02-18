import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { DashboardTemplateVariableType, InsightType } from '~/types'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'
import { newDashboardLogic } from './newDashboardLogic'

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

export function DashboardTemplateVariables(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)

    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { setVariables, updateVariable } = useActions(dashboardTemplateVariablesLogic)

    useEffect(() => {
        setVariables(activeDashboardTemplate?.variables || [])
    }, [activeDashboardTemplate])

    return (
        <div>
            <div>
                {variables.map((variable, index) => (
                    <div key={index}>
                        <div key={variable.name}>
                            <span>{variable.name}</span>{' '}
                            {variable.required !== undefined && (
                                <span
                                    style={{
                                        color: variable.required ? 'red' : 'green',
                                    }}
                                >
                                    {variable.required ? 'required' : 'optional'}
                                </span>
                            )}
                        </div>
                        <div>
                            <ActionFilter
                                filters={{
                                    insight: InsightType.TRENDS,
                                    events: [variable.default],
                                }}
                                setFilters={(filters) => {
                                    console.log(variable.name, filters)
                                    updateVariable(variable.name, filters)
                                }}
                                typeKey={'variable_' + variable.name}
                                buttonCopy={''}
                                hideDeleteBtn={true}
                                hideRename={true}
                                hideDuplicate={true}
                                entitiesLimit={1}
                            />
                        </div>
                    </div>
                ))}
            </div>
            {/* <LemonButton onClick={createDashboard}>Create dashboard</LemonButton> */}
        </div>
    )
}
