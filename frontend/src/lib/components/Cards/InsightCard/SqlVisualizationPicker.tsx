import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { columnsFromResponse, getAutoVisualizationType } from '~/queries/nodes/DataVisualization/columnUtils'
import {
    getTableDisplayOptions,
    renderDisplayTypeLabel,
} from '~/queries/nodes/DataVisualization/Components/tableDisplayOptions'
import { DataVisualizationNode, Node } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

export interface SqlVisualizationPickerProps {
    query: DataVisualizationNode
    insightData: Record<string, any>
    persistDisplayOptions: (node: Node) => void
}

// A dashboard card renders its query read-only, which drops the setQuery that dataVisualizationLogic
// would normally persist through. So save the picked type straight onto the insight instead.
export function SqlVisualizationPicker({
    query,
    insightData,
    persistDisplayOptions,
}: SqlVisualizationPickerProps): JSX.Element {
    const columns = useMemo(() => columnsFromResponse(insightData), [insightData])
    const numericalColumns = useMemo(() => columns.filter((column) => column.type.isNumerical), [columns])
    const autoVisualizationType = useMemo(() => getAutoVisualizationType(columns, insightData), [columns, insightData])

    const visualizationType = query.display ?? ChartDisplayType.ActionsTable

    return (
        <LemonSelect
            className="pb-2 px-2"
            fullWidth
            size="small"
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            onChange={(value) => {
                const nextQuery: DataVisualizationNode = { ...query, display: value }
                persistDisplayOptions(nextQuery)
            }}
            options={getTableDisplayOptions(columns, numericalColumns, autoVisualizationType)}
            dropdownMatchSelectWidth={false}
            optionTooltipPlacement="left"
            data-attr="dashboard-insight-visualization-picker"
        />
    )
}
