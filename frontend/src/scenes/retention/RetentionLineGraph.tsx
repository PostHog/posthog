import React, { useState } from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph'
import { useValues } from 'kea'
import { Loading } from '../../lib/utils'
import { router } from 'kea-router'
import { LineGraphEmptyState } from '../insights/EmptyStates'

interface RetentionLineGraphProps {
    dashboardItemId?: number | null
    color?: string
    inSharedMode?: boolean | null
}

export function RetentionLineGraph({
    dashboardItemId = null,
    color = 'white',
    inSharedMode = false,
}: RetentionLineGraphProps): JSX.Element {
    const logic = retentionTableLogic({ dashboardItemId: dashboardItemId })
    const { filters, retention, retentionLoading } = useValues(logic)
    const [{ fromItem }] = useState(router.values.hashParams)

    return retentionLoading ? (
        <Loading />
    ) : retention && retention.data && !retentionLoading ? (
        <LineGraph
            pageKey={'trends-annotations'}
            data-attr="trend-line-graph"
            type="line"
            color={color}
            datasets={retention.data}
            labels={(retention.data[0] && retention.data[0].labels) || []}
            isInProgress={!filters.selectedDate}
            dashboardItemId={dashboardItemId || fromItem}
            inSharedMode={inSharedMode}
            percentage={true}
            onClick={() => {}}
        />
    ) : (
        <LineGraphEmptyState color={color} />
    )
}
