// This file contains funnel-related components that are used in the general insights scope
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { Button } from 'antd'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import './FunnelCanvasLabel.scss'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { ChartDisplayType } from '~/types'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { conversionMetrics } = useValues(funnelLogic)
    const { allFilters } = useValues(insightLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    if (allFilters.insight !== 'FUNNELS') {
        return null
    }

    return (
        <div className="funnel-canvas-label">
            {allFilters.display === ChartDisplayType.FunnelViz && (
                <>
                    <span className="text-muted-alt">Total conversion rate: </span>
                    <span>{conversionMetrics.totalRate}%</span>
                    <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />
                </>
            )}
            {allFilters.display === ChartDisplayType.FunnelsTimeToConvert && (
                <>
                    <span className="text-muted-alt">Total time to convert: </span>
                    <span>{humanFriendlyDuration(conversionMetrics.totalTime)}</span>
                    <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />
                </>
            )}
            <span className="text-muted-alt">Mean time to convert: </span>
            <Button
                type="link"
                disabled={allFilters.display === ChartDisplayType.FunnelsTimeToConvert}
                onClick={() => setChartFilter(ChartDisplayType.FunnelsTimeToConvert)}
            >
                {humanFriendlyDuration(conversionMetrics.averageTime)}
            </Button>
        </div>
    )
}
