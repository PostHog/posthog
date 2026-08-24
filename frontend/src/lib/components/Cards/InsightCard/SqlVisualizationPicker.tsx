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
     * while these keep their identity, which is what stops the menu remounting. */
    columns?: string[] | null
    types?: string[][] | null
    /** Row count, not the rows. Auto picks a time series only when there is more than one. */
    rowCount?: number
    disabledReason?: string | null
    persistDisplayOptions: (node: Node) => void
}

/** `axes` needs columns on an x and a y. `manual` needs columns assigned to named roles that no rule
 * can guess, so a card cannot offer it at all. `none` draws without axes. */
type CardSupport = 'none' | 'axes' | 'manual'

// Exhaustive on purpose: adding a chart type is a type error here, so a new one cannot reach a card
// unclassified and save a query the tile has no settings to draw.
const CARD_SUPPORT: Record<ChartDisplayType, CardSupport> = {
    [ChartDisplayType.Auto]: 'none',
    [ChartDisplayType.ActionsTable]: 'none',
    [ChartDisplayType.BoldNumber]: 'none',
    [ChartDisplayType.ActionsLineGraph]: 'axes',
    [ChartDisplayType.ActionsAreaGraph]: 'axes',
    [ChartDisplayType.ActionsBar]: 'axes',
    [ChartDisplayType.ActionsStackedBar]: 'axes',
    [ChartDisplayType.ActionsUnstackedBar]: 'axes',
    [ChartDisplayType.ActionsPie]: 'axes',
    [ChartDisplayType.ActionsLineGraphCumulative]: 'axes',
    [ChartDisplayType.ScatterPlot]: 'manual',
    [ChartDisplayType.TwoDimensionalHeatmap]: 'manual',
    // Not offered by the SQL list, but the map has to cover the enum.
    [ChartDisplayType.ActionsBarValue]: 'manual',
    [ChartDisplayType.Metric]: 'manual',
    [ChartDisplayType.WorldMap]: 'manual',
    [ChartDisplayType.CalendarHeatmap]: 'manual',
    [ChartDisplayType.BoxPlot]: 'manual',
    [ChartDisplayType.SlopeGraph]: 'manual',
}

const MANUAL_SETUP_REASON = 'Open the insight to pick which column goes on each axis'
const NO_NUMERIC_COLUMN_REASON = 'This insight has no numeric column to plot'
const NO_X_AXIS_COLUMN_REASON = 'This insight has no column left to label the x axis'

function resolveDisplayType(displayType: ChartDisplayType, autoVisualizationType: ChartDisplayType): ChartDisplayType {
    return displayType === ChartDisplayType.Auto ? autoVisualizationType : displayType
}

// The editor moves the first numeric column onto the x axis when every column is numeric, but only
// for a line or an area chart. The card follows that, so the same pick saves the same axes on both.
const PROMOTES_FIRST_NUMERIC_TO_X = [ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsAreaGraph]

function axesFor(columns: Column[], drawnAs: ChartDisplayType): { xAxis: string | null; yAxis: string[] } {
    const defaults = deriveDefaultAxes(columns)
    const allNumeric = columns.length > 1 && columns.every((column) => column.type.isNumerical)

    if (defaults.xAxis || !allNumeric || !PROMOTES_FIRST_NUMERIC_TO_X.includes(drawnAs)) {
        return defaults
    }

    const [first, ...rest] = columns
    return { xAxis: first.name, yAxis: rest.map((column) => column.name) }
}

// A chart reads its columns out of chartSettings, and loading the saved query resets the axes to
// whatever it carries. So a query saved as a table has to gain axes here, or the chart draws empty.
export function withAxes(
    query: DataVisualizationNode,
    columns: Column[],
    autoVisualizationType: ChartDisplayType
): DataVisualizationNode {
    const drawnAs = query.display ? resolveDisplayType(query.display, autoVisualizationType) : undefined
    if (!drawnAs || CARD_SUPPORT[drawnAs] !== 'axes') {
        return query
    }

    const { xAxis, yAxis } = axesFor(columns, drawnAs)
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

// The one rule for what a card can switch a SQL insight to. It answers by running the save it would
// perform, so an offered type is always one the card can complete.
export function cardVisualizationDisabledReason(
    displayType: ChartDisplayType,
    query: DataVisualizationNode,
    columns: Column[],
    autoVisualizationType: ChartDisplayType
): string | undefined {
    const drawnAs = resolveDisplayType(displayType, autoVisualizationType)

    if (CARD_SUPPORT[drawnAs] === 'manual') {
        return displayType === ChartDisplayType.Auto
            ? `Auto picks a chart here that needs its axes set. ${MANUAL_SETUP_REASON}.`
            : MANUAL_SETUP_REASON
    }

    if (CARD_SUPPORT[drawnAs] !== 'axes') {
        return undefined
    }

    const saved = withAxes({ ...query, display: displayType }, columns, autoVisualizationType)
    if (saved.chartSettings?.xAxis && saved.chartSettings.yAxis?.length) {
        return undefined
    }

    return deriveDefaultAxes(columns).yAxis.length === 0 ? NO_NUMERIC_COLUMN_REASON : NO_X_AXIS_COLUMN_REASON
}

// A dashboard card renders its query read-only, which drops the setQuery that dataVisualizationLogic
// persists through. So save the picked type straight onto the insight instead.
export function SqlVisualizationPicker({
    query,
    columns: responseColumns,
    types,
    rowCount,
    disabledReason,
    persistDisplayOptions,
}: SqlVisualizationPickerProps): JSX.Element {
    const response = useMemo(
        () => ({
            columns: responseColumns ?? [],
            types: types ?? [],
            // getAutoVisualizationType only reads the row count, so a stand-in of that length is enough.
            result: new Array(rowCount ?? 0),
        }),
        [responseColumns, types, rowCount]
    )
    const columns = useMemo(() => columnsFromResponse(response), [response])
    const numericalColumns = useMemo(() => columns.filter((column) => column.type.isNumerical), [columns])
    const autoVisualizationType = useMemo(() => getAutoVisualizationType(columns, response), [columns, response])

    const disabledReasonFor = useCallback(
        (displayType: ChartDisplayType) =>
            cardVisualizationDisabledReason(displayType, query, columns, autoVisualizationType),
        [query, columns, autoVisualizationType]
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
            disabledReason={disabledReason ?? (columns.length ? undefined : 'This insight has no results to visualize')}
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
