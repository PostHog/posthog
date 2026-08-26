import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { DashboardType } from '~/types'

import { Variable } from '../../types'
import { variablesLogic } from '../Variables/variablesLogic'
import { SqlChart, SqlChartProps } from './SqlChart'

/**
 * The variable a click on a data point should fill. A click carries a text category, so only a String
 * or List variable can take it. The value maps reliably only when the query uses exactly one such
 * variable; zero or several candidates return null, which leaves the chart inert.
 */
export function singleFilterableVariable(variablesUsedInQuery: Variable[]): Variable | null {
    const candidates = variablesUsedInQuery.filter((v) => v.type === 'String' || v.type === 'List')
    return candidates.length === 1 ? candidates[0] : null
}

/**
 * SQL chart on a dashboard tile. A click on a data point overrides a dashboard variable with the
 * clicked category value, the same push {@link dashboardLogic.overrideVariableValue} does for the
 * manual variable dropdown, so every tile re-filters at once.
 */
export function SqlChartWithDashboardVariables({
    dashboardId,
    ...props
}: SqlChartProps & { dashboardId: DashboardType['id'] }): JSX.Element {
    const { overrideVariableValue } = useActions(dashboardLogic({ id: dashboardId }))
    const { variablesUsedInQuery } = useValues(variablesLogic)

    // Public shares stay inert: a click there must not mutate the dashboard.
    const targetVariable = useMemo(
        () => (isSharedView() ? null : singleFilterableVariable(variablesUsedInQuery)),
        [variablesUsedInQuery]
    )

    const onPointClick = useCallback(
        (_seriesKey: string, _dataIndex: number, label: string): void => {
            if (targetVariable) {
                overrideVariableValue(targetVariable.id, label, false)
            }
        },
        [targetVariable, overrideVariableValue]
    )

    if (!targetVariable) {
        return <SqlChart {...props} />
    }

    return (
        <SqlChart {...props} onPointClick={onPointClick} pointClickHint={`Click to filter by ${targetVariable.name}`} />
    )
}
