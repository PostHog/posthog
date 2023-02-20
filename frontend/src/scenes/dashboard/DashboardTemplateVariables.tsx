import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { InsightType } from '~/types'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'
import { newDashboardLogic } from './newDashboardLogic'

export function DashboardTemplateVariables(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)

    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { setVariables, updateVariable } = useActions(dashboardTemplateVariablesLogic)

    useEffect(() => {
        setVariables(activeDashboardTemplate?.variables || [])
    }, [activeDashboardTemplate])

    return (
        <div className="mt-4 mb-6">
            {variables.map((variable, index) => (
                <div key={index}>
                    <div key={variable.name}>
                        <strong>{variable.name}</strong>{' '}
                        {variable.required !== undefined && (
                            <span
                                style={{
                                    color: variable.required ? 'red' : 'green',
                                }}
                            >
                                {variable.required ? 'required' : 'optional'}
                            </span>
                        )}
                        <p>{variable.description}</p>
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
    )
}
