import { LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
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
    const { setVariable } = useActions(theDashboardTemplateVariablesLogic)

    return (
        <div className="mb-4 DashboardTemplateVariables max-w-md">
            {variables.map((variable, index) => (
                <div key={index} className="mb-6">
                    <div className="mb-2">
                        <LemonLabel showOptional={!variable.required} info={<>{variable.description}</>}>
                            {variable.name}
                        </LemonLabel>
                        <p className="text-sm text-muted">{variable.description}</p>
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
