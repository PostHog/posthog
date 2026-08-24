import { useEffect, useMemo, useState } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import {
    columnsFromResponse,
    deriveDefaultAxes,
    getAutoVisualizationType,
} from '~/queries/nodes/DataVisualization/columnUtils'
import {
    getTableDisplayOptions,
    renderDisplayTypeLabel,
} from '~/queries/nodes/DataVisualization/Components/tableDisplayOptions'
import { Column } from '~/queries/nodes/DataVisualization/types'
import { DataVisualizationNode, Node } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

export interface SqlVisualizationPickerProps {
    query: DataVisualizationNode
    /** Taken apart rather than passed whole: the response object is rebuilt on every refresh tick,
     * while these arrays keep their identity, which is what stops the menu remounting. */
    columns?: string[] | null
    types?: string[][] | null
    result?: unknown
    persistDisplayOptions: (node: Node) => void
}

// Only these plot columns against axes. The rest ignore chartSettings, so picking one should not
// write axes into the saved insight.
const AXIS_PLOTTING_TYPES = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsStackedBar,
    ChartDisplayType.ActionsPie,
]

// A chart reads its columns out of chartSettings, and loading the saved query resets the axes to
// whatever it carries. So a query saved as a table has to gain axes here, or the chart draws empty.
function withAxes(query: DataVisualizationNode, columns: Column[]): DataVisualizationNode {
    if (!query.display || !AXIS_PLOTTING_TYPES.includes(query.display)) {
        return query
    }

    if (query.chartSettings?.xAxis || query.chartSettings?.yAxis?.length) {
        return query
    }

    const { xAxis, yAxis } = deriveDefaultAxes(columns)
    if (!xAxis || yAxis.length === 0) {
        return query
    }

    return {
        ...query,
        chartSettings: {
            ...query.chartSettings,
            xAxis: { column: xAxis },
            yAxis: yAxis.map((column) => ({ column })),
        },
    }
}

// A dashboard card renders its query read-only, which drops the setQuery that dataVisualizationLogic
// persists through. So save the picked type straight onto the insight instead.
export function SqlVisualizationPicker({
    query,
    columns: responseColumns,
    types,
    result,
    persistDisplayOptions,
}: SqlVisualizationPickerProps): JSX.Element {
    const response = useMemo(
        () => ({ columns: responseColumns ?? [], types: types ?? [], result }),
        [responseColumns, types, result]
    )
    const columns = useMemo(() => columnsFromResponse(response), [response])
    const numericalColumns = useMemo(() => columns.filter((column) => column.type.isNumerical), [columns])
    const autoVisualizationType = useMemo(() => getAutoVisualizationType(columns, response), [columns, response])
    const options = useMemo(
        () =>
            getTableDisplayOptions(
                columns,
                numericalColumns,
                autoVisualizationType,
                'Pick this in the insight, so you can choose which column goes on each axis'
            ),
        [columns, numericalColumns, autoVisualizationType]
    )

    // The save is debounced and then round trips, so show the pick straight away rather than leaving
    // the menu on the old value for a second. Drop it once the saved query catches up, so a save that
    // failed or was skipped stops the control claiming a change that never landed.
    const [pending, setPending] = useState<ChartDisplayType | null>(null)
    useEffect(() => setPending(null), [query.display])

    const visualizationType = pending ?? query.display ?? ChartDisplayType.ActionsTable
    const hasColumns = columns.length > 0

    return (
        <LemonSelect
            className="pb-2 px-2"
            fullWidth
            size="small"
            disabledReason={hasColumns ? undefined : 'This insight has no columns to visualize yet'}
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            onChange={(value) => {
                setPending(value)
                persistDisplayOptions(withAxes({ ...query, display: value }, columns))
            }}
            options={options}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
