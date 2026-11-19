import { useActions, useValues } from 'kea'

import { dashboardV2Logic } from './dashboardV2Logic'
import { DashboardV2VariableControl } from './DashboardV2VariableControl'

export function DashboardV2Variables(): JSX.Element | null {
    const { visibleVariables, variableValues } = useValues(dashboardV2Logic)
    const { setVariable } = useActions(dashboardV2Logic)

    if (!visibleVariables.length) {
        return null
    }
    return (
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2" data-attr="dashboard-v2-variables">
            {visibleVariables.map((variable) => (
                <DashboardV2VariableControl
                    key={variable.name}
                    variable={variable}
                    values={variableValues[variable.name] ?? []}
                    onChange={(values) => setVariable(variable.name, values)}
                />
            ))}
        </div>
    )
}
