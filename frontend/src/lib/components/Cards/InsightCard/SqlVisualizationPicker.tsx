import { useCallback, useEffect, useMemo, useState } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { columnsFromResponse, getAutoVisualizationType } from '~/queries/nodes/DataVisualization/columnUtils'
import {
    getTableDisplayOptions,
    renderDisplayTypeLabel,
} from '~/queries/nodes/DataVisualization/Components/tableDisplayOptions'
import { Column } from '~/queries/nodes/DataVisualization/types'
import { applyVisualizationType } from '~/queries/nodes/DataVisualization/visualizationTypeSetup'
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
    /** Distinguishes a tile still computing from one that genuinely returned nothing. */
    loading?: boolean
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

// The one rule for what a card can switch a SQL insight to. It answers by running the setup the save
// would perform, so an offered type is always one the card can complete.
export function cardVisualizationDisabledReason(
    displayType: ChartDisplayType,
    query: DataVisualizationNode,
    columns: Column[],
    rowCount: number,
    autoVisualizationType: ChartDisplayType
): string | undefined {
    const drawnAs = displayType === ChartDisplayType.Auto ? autoVisualizationType : displayType

    if (CARD_SUPPORT[drawnAs] === 'manual') {
        return displayType === ChartDisplayType.Auto
            ? `Auto picks a chart here that needs its axes set. ${MANUAL_SETUP_REASON}.`
            : MANUAL_SETUP_REASON
    }

    if (CARD_SUPPORT[drawnAs] !== 'axes') {
        return undefined
    }

    // Ask what the save would produce, then name whichever axis it could not fill, rather than
    // guessing from the columns alone.
    const saved = applyVisualizationType(query, displayType, columns, rowCount)
    if (saved.chartSettings?.xAxis && saved.chartSettings.yAxis?.length) {
        return undefined
    }

    return saved.chartSettings?.yAxis?.length ? NO_X_AXIS_COLUMN_REASON : NO_NUMERIC_COLUMN_REASON
}

// A dashboard card renders its query read-only, which drops the setQuery that dataVisualizationLogic
// persists through. So save the picked type straight onto the insight instead.
export function SqlVisualizationPicker({
    query,
    columns: responseColumns,
    types,
    rowCount,
    loading,
    disabledReason,
    persistDisplayOptions,
}: SqlVisualizationPickerProps): JSX.Element {
    const columns = useMemo(
        () => columnsFromResponse({ columns: responseColumns ?? [], types: types ?? [] }),
        [responseColumns, types]
    )
    const numericalColumns = useMemo(() => columns.filter((column) => column.type.isNumerical), [columns])
    const rows = rowCount ?? 0
    const autoVisualizationType = useMemo(() => getAutoVisualizationType(columns, rows), [columns, rows])

    const disabledReasonFor = useCallback(
        (displayType: ChartDisplayType) =>
            cardVisualizationDisabledReason(displayType, query, columns, rows, autoVisualizationType),
        [query, columns, rows, autoVisualizationType]
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
            disabledReason={
                disabledReason ??
                (columns.length
                    ? undefined
                    : loading
                      ? 'Waiting for this insight to load'
                      : 'This insight returned no columns to visualize')
            }
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            onChange={(value) => {
                setPending(value)
                persistDisplayOptions(applyVisualizationType(query, value, columns, rows))
            }}
            options={options}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
