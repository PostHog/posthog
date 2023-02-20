import { LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { FilterType, InsightType } from '~/types'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'
import { newDashboardLogic } from './newDashboardLogic'

export function DashboardTemplateVariables(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)

    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { setVariables, updateVariable } = useActions(dashboardTemplateVariablesLogic)

    const FALLBACK_EVENT = {
        id: '$pageview',
        math: 'dau',
        type: 'events',
    }

    useEffect(() => {
        setVariables(activeDashboardTemplate?.variables || [])
    }, [activeDashboardTemplate])

    return (
        <div
            className="mb-4"
            style={{
                maxWidth: 600,
            }}
        >
            {variables.map((variable, index) => (
                <div key={index} className="mb-6">
                    <div className="mb-2">
                        <LemonLabel
                            showOptional={!variable.required}
                            // info={variable.description} TODO: fix info, currently not working
                        >
                            {variable.name}
                        </LemonLabel>
                        <p className="text-sm text-muted">{variable.description}</p>
                    </div>
                    <div>
                        <ActionFilter
                            filters={{
                                insight: InsightType.TRENDS,
                                events: variable.default ? [variable.default] : [FALLBACK_EVENT],
                            }}
                            setFilters={(filters: FilterType) => {
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
