import { useMemo, useState } from 'react'

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
    insightData: Record<string, any>
    persistDisplayOptions: (node: Node) => void
}

// A chart reads its columns out of chartSettings, and loading the saved query resets the axes to
// whatever it carries. So a query saved as a table has to gain axes here, or the chart draws empty.
function withAxes(query: DataVisualizationNode, columns: Column[]): DataVisualizationNode {
    if (query.chartSettings?.xAxis || query.chartSettings?.yAxis?.length) {
        return query
    }

    const { xAxis, yAxis } = deriveDefaultAxes(columns)
    if (!xAxis && yAxis.length === 0) {
        return query
    }

    return {
        ...query,
        chartSettings: {
            ...query.chartSettings,
            ...(xAxis ? { xAxis: { column: xAxis } } : {}),
            yAxis: yAxis.map((column) => ({ column })),
        },
    }
}

// A dashboard card renders its query read-only, which drops the setQuery that dataVisualizationLogic
// persists through. So save the picked type straight onto the insight instead.
export function SqlVisualizationPicker({
    query,
    insightData,
    persistDisplayOptions,
}: SqlVisualizationPickerProps): JSX.Element {
    const columns = useMemo(() => columnsFromResponse(insightData), [insightData])
    const numericalColumns = useMemo(() => columns.filter((column) => column.type.isNumerical), [columns])
    const autoVisualizationType = useMemo(() => getAutoVisualizationType(columns, insightData), [columns, insightData])

    // The save is debounced and then round trips, so show the pick straight away rather than leaving
    // the menu on the old value for a second.
    const [pending, setPending] = useState<ChartDisplayType | null>(null)
    const visualizationType = pending ?? query.display ?? ChartDisplayType.ActionsTable

    const hasColumns = columns.length > 0

    return (
        <LemonSelect
            className="pb-2 px-2"
            fullWidth
            size="small"
            disabledReason={hasColumns ? undefined : 'Waiting for this insight to load'}
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            onChange={(value) => {
                setPending(value)
                persistDisplayOptions(withAxes({ ...query, display: value }, columns))
            }}
            options={getTableDisplayOptions(
                columns,
                numericalColumns,
                autoVisualizationType,
                'Pick this in the insight, so you can choose which column goes on each axis'
            )}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
