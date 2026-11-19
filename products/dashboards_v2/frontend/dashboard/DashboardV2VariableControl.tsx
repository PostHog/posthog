import { Button } from '@posthog/quill'

import { DashboardV2MultiSelectVariable } from './DashboardV2MultiSelectVariable'
import { DashboardV2SelectVariable } from './DashboardV2SelectVariable'
import { DashboardV2TextVariable } from './DashboardV2TextVariable'
import { ALL_VALUE, type DashboardV2Variable, variableOptions } from './variables'

interface DashboardV2VariableControlProps {
    variable: DashboardV2Variable
    values: string[]
    onChange: (values: string[]) => void
}

export function DashboardV2VariableControl({
    variable,
    values,
    onChange,
}: DashboardV2VariableControlProps): JSX.Element | null {
    const label = variable.label || variable.name
    const options = variableOptions(variable)

    if (variable.type === 'textbox') {
        return <DashboardV2TextVariable label={label} value={values[0] ?? ''} onChange={(value) => onChange([value])} />
    }
    if (options && variable.multi) {
        return (
            <DashboardV2MultiSelectVariable
                label={label}
                options={options}
                includeAll={!!variable.includeAll}
                values={values}
                onChange={onChange}
            />
        )
    }
    if (options) {
        return (
            <DashboardV2SelectVariable
                name={variable.name}
                label={label}
                options={options}
                includeAll={!!variable.includeAll}
                value={values[0]}
                onChange={(value) => onChange([value])}
            />
        )
    }
    if (variable.type === 'query') {
        const shown = values.includes(ALL_VALUE) ? 'All' : values.join(', ') || 'Not set'
        return (
            <Button
                variant="outline"
                className="max-w-64"
                disabledReason="This filter gets its options from a query. Queries do not run on this page yet."
                data-attr="dashboard-v2-variable-query"
            >
                <span>{label}:</span>
                <span className="truncate" translate="no">
                    {shown}
                </span>
            </Button>
        )
    }
    return null
}
