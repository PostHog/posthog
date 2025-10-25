import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'

import { FilterType, InsightType } from '~/types'

import { dashboardTemplateVariablesLogic } from './dashboardTemplateVariablesLogic'
import { newDashboardLogic } from './newDashboardLogic'

export function DashboardTemplateVariables(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const theDashboardTemplateVariablesLogic = dashboardTemplateVariablesLogic({
        variables: activeDashboardTemplate?.variables || [],
    })
    const { variables } = useValues(theDashboardTemplateVariablesLogic)
    const { setVariable, setVariables } = useActions(theDashboardTemplateVariablesLogic)

    // this is a hack, I'm not sure why it's not set properly initially. Figure it out.
    useEffect(() => {
        setVariables(activeDashboardTemplate?.variables || [])
    }, [activeDashboardTemplate]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="mb-4 DashboardTemplateVariables max-w-192">
            {variables.map((variable, index) => (
                <div key={index} className="mb-6">
                    <div className="mb-2">
                        <LemonLabel showOptional={!variable.required} info={<>{variable.description}</>}>
                            {variable.name}
                        </LemonLabel>
                        <p className="text-sm text-secondary">{variable.description}</p>
                    </div>
                    <div>
                        <ActionFilter
                            filters={{
                                insight: InsightType.TRENDS,
                                events: [variable.default],
                            }}
                            setFilters={(filters: FilterType) => {
                                setVariable(variable.name, filters)
                            }}
                            typeKey={'variable_' + variable.name}
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
