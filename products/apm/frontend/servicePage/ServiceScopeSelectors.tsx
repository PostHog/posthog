import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import type { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'

import { TIME_RANGE_LABELS, TimeRange } from '../applicationObservabilityLogic'
import { environmentOptions } from '../environmentDisplay'
import type { ServiceScope } from './servicePage'
import { servicePageLogic } from './servicePageLogic'

function scopeOptions(values: string[], selected: string | null): LemonSelectOptionLeaf<string | null>[] {
    // Keep a value from the URL selectable even when this window has no spans for it.
    const all = selected && !values.includes(selected) ? [selected, ...values] : values
    return [{ value: null, label: 'All' }, ...all.map((value) => ({ value, label: value }))]
}

export function ServiceScopeSelectors({ serviceName }: { serviceName: string }): JSX.Element {
    const logic = servicePageLogic({ serviceName })
    const {
        timeRange,
        scope,
        environments,
        servicesHealthLoading,
        scopeOptions: options,
        scopeOptionsLoading,
        operationNames,
        endpointsHealthLoading,
    } = useValues(logic)
    const { setScope, setTimeRange } = useActions(logic)

    const selector = (
        field: keyof ServiceScope,
        label: string,
        choices: LemonSelectOptionLeaf<string | null>[],
        loading: boolean
    ): JSX.Element => (
        <div className="flex items-center gap-1">
            <span className="text-xs text-muted">{label}</span>
            <LemonSelect<string | null>
                size="small"
                value={scope[field]}
                options={choices}
                onChange={(value) => setScope({ [field]: value })}
                loading={loading}
                dropdownMatchSelectWidth={false}
                data-attr={`apm-service-scope-${field}`}
            />
        </div>
    )

    return (
        <div className="flex flex-wrap items-center gap-3">
            <LemonSelect
                size="small"
                value={timeRange}
                onChange={(value) => setTimeRange(value as TimeRange)}
                options={(Object.keys(TIME_RANGE_LABELS) as TimeRange[]).map((value) => ({
                    value,
                    label: TIME_RANGE_LABELS[value],
                }))}
                data-attr="apm-service-time-range"
            />
            {selector(
                'environment',
                'Environment',
                environmentOptions(environments, scope.environment),
                servicesHealthLoading
            )}
            {selector('version', 'Version', scopeOptions(options.versions, scope.version), scopeOptionsLoading)}
            {selector('operation', 'Operation', scopeOptions(operationNames, scope.operation), endpointsHealthLoading)}
        </div>
    )
}
