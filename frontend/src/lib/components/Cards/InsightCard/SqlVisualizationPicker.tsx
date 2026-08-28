import { useCallback, useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { columnsFromResponse, getAutoVisualizationType } from '~/queries/nodes/DataVisualization/columnUtils'
import {
    getTableDisplayOptions,
    renderDisplayTypeLabel,
} from '~/queries/nodes/DataVisualization/Components/tableDisplayOptions'
import { sqlVisualizationDisabledReason } from '~/queries/nodes/DataVisualization/sqlVisualizationSupport'
import { DataVisualizationNode } from '~/queries/schema/schema-general'
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
    /** True while a pick is being saved. */
    saving?: boolean
    disabledReason?: string | null
    persistVisualizationType: (display: ChartDisplayType) => void
}

// A dashboard card renders its query read-only, which drops the setQuery that dataVisualizationLogic
// persists through. So save the picked type straight onto the insight instead.
export function SqlVisualizationPicker({
    query,
    columns: responseColumns,
    types,
    rowCount,
    loading,
    saving,
    disabledReason,
    persistVisualizationType,
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
            sqlVisualizationDisabledReason(displayType, query, columns, rows, autoVisualizationType),
        [query, columns, rows, autoVisualizationType]
    )
    const options = useMemo(
        () => getTableDisplayOptions(columns, numericalColumns, autoVisualizationType, disabledReasonFor),
        [columns, numericalColumns, autoVisualizationType, disabledReasonFor]
    )

    const visualizationType = query.display ?? ChartDisplayType.ActionsTable

    return (
        <LemonSelect
            className="pb-2 px-2"
            fullWidth
            size="small"
            loading={saving}
            disabledReason={
                disabledReason ??
                (saving
                    ? 'Saving chart type'
                    : loading
                      ? 'Waiting for this insight to load'
                      : columns.length
                        ? undefined
                        : 'This insight returned no columns to visualize')
            }
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            onChange={(value) => {
                persistVisualizationType(value)
            }}
            options={options}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
