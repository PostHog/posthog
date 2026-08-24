import { useCallback, useEffect, useMemo, useState } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { columnsFromResponse, getAutoVisualizationType } from '~/queries/nodes/DataVisualization/columnUtils'
import {
    getTableDisplayOptions,
    renderDisplayTypeLabel,
} from '~/queries/nodes/DataVisualization/Components/tableDisplayOptions'
import { DataVisualizationNode, Node } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { cardVisualizationDisabledReason, withAxes } from './cardVisualizationSupport'

export interface SqlVisualizationPickerProps {
    query: DataVisualizationNode
    /** Taken apart rather than passed whole: the response object is rebuilt on every refresh tick,
     * while these arrays keep their identity, which is what stops the menu remounting. */
    columns?: string[] | null
    types?: string[][] | null
    result?: unknown
    persistDisplayOptions: (node: Node) => void
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
                persistDisplayOptions(withAxes({ ...query, display: value }, columns, autoVisualizationType))
            }}
            options={options}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
