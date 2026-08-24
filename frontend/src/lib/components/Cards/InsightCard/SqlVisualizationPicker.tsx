import { useCallback, useEffect, useMemo, useState } from 'react'

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

// These plot columns against axes, so a card can only offer them when it can derive both.
export const AXIS_PLOTTING_TYPES = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsStackedBar,
    ChartDisplayType.ActionsPie,
]

// These need columns assigned to named roles that no rule can guess, and a card has no control for it.
const NEEDS_MANUAL_SETUP = [ChartDisplayType.ScatterPlot, ChartDisplayType.TwoDimensionalHeatmap]

const MANUAL_SETUP_REASON = 'Open the insight to pick which column goes on each axis'
const NO_PLOTTABLE_COLUMNS_REASON = 'This insight has no numeric column to plot'

function resolveDisplayType(displayType: ChartDisplayType, autoVisualizationType: ChartDisplayType): ChartDisplayType {
    return displayType === ChartDisplayType.Auto ? autoVisualizationType : displayType
}

// The one rule for what a card can switch a SQL insight to. Both the option list and the query it
// saves answer to this, so an offered type is always one the card can complete.
export function cardVisualizationDisabledReason(
    displayType: ChartDisplayType,
    columns: Column[],
    autoVisualizationType: ChartDisplayType
): string | undefined {
    const drawnAs = resolveDisplayType(displayType, autoVisualizationType)

    if (NEEDS_MANUAL_SETUP.includes(drawnAs)) {
        // Auto resolves from the columns, so the reason has to name that rather than the pick.
        return displayType === ChartDisplayType.Auto
            ? `This insight defaults to a chart that needs its axes picked. ${MANUAL_SETUP_REASON}`
            : MANUAL_SETUP_REASON
    }

    if (AXIS_PLOTTING_TYPES.includes(drawnAs) && !hasDerivableAxes(columns)) {
        return NO_PLOTTABLE_COLUMNS_REASON
    }

    return undefined
}

function hasDerivableAxes(columns: Column[]): boolean {
    const { xAxis, yAxis } = deriveDefaultAxes(columns)
    return !!xAxis && yAxis.length > 0
}

// A chart reads its columns out of chartSettings, and loading the saved query resets the axes to
// whatever it carries. So a query saved as a table has to gain axes here, or the chart draws empty.
export function withAxes(
    query: DataVisualizationNode,
    columns: Column[],
    autoVisualizationType: ChartDisplayType
): DataVisualizationNode {
    const drawnAs = query.display ? resolveDisplayType(query.display, autoVisualizationType) : undefined
    if (!drawnAs || !AXIS_PLOTTING_TYPES.includes(drawnAs)) {
        return query
    }

    const { xAxis, yAxis } = deriveDefaultAxes(columns)
    // Fill only the side the query is missing, so axes the user chose stay untouched.
    const nextXAxis = query.chartSettings?.xAxis ?? (xAxis ? { column: xAxis } : undefined)
    const nextYAxis = query.chartSettings?.yAxis?.length
        ? query.chartSettings.yAxis
        : yAxis.map((column) => ({ column }))

    if (!nextXAxis || nextYAxis.length === 0) {
        return query
    }

    return { ...query, chartSettings: { ...query.chartSettings, xAxis: nextXAxis, yAxis: nextYAxis } }
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

    const disabledReasonFor = useCallback(
        (displayType: ChartDisplayType) => cardVisualizationDisabledReason(displayType, columns, autoVisualizationType),
        [columns, autoVisualizationType]
    )
    const options = useMemo(
        () => getTableDisplayOptions(columns, numericalColumns, autoVisualizationType, disabledReasonFor),
        [columns, numericalColumns, autoVisualizationType, disabledReasonFor]
    )

    // The save is debounced and then round trips, so show the pick straight away rather than leaving
    // the menu on the old value for a second. The held value goes once the saved query catches up.
    // A save that fails keeps showing the attempted type until the tile reloads, and the failure
    // toast is the signal for that.
    const [pending, setPending] = useState<ChartDisplayType | null>(null)
    useEffect(() => setPending(null), [query.display])

    const visualizationType = pending ?? query.display ?? ChartDisplayType.ActionsTable

    return (
        <LemonSelect
            className="pb-2 px-2"
            fullWidth
            size="small"
            disabledReason={columns.length ? undefined : 'This insight has no columns to visualize yet'}
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            onChange={(value) => {
                setPending(value)
                persistDisplayOptions(withAxes({ ...query, display: value }, columns, autoVisualizationType))
            }}
            options={options}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
