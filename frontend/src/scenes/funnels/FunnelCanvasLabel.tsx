// This file contains funnel-related components that are used in the general insights scope
import { useActions, useValues } from 'kea'
import { FUNNELS_TIME_TO_CONVERT, FUNNEL_VIZ } from 'lib/constants'
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
            {allFilters.display === FUNNEL_VIZ && (
                <>
                    <span className="text-muted-alt">Total conversion rate: </span>
                    <span>{conversionMetrics.totalRate}%</span>
                    <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />
                </>
            )}
            {allFilters.display === FUNNELS_TIME_TO_CONVERT && (
                <>
                    <span className="text-muted-alt">Total time to convert: </span>
                    <span>{humanFriendlyDuration(conversionMetrics.sum)}</span>
                    <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />
                </>
            )}
            <span className="text-muted-alt">Mean time to convert: </span>
            <Button
                type="link"
                disabled={allFilters.display === FUNNELS_TIME_TO_CONVERT}
                onClick={() => setChartFilter(ChartDisplayType.FunnelsTimeToConvert)}
            >
                {humanFriendlyDuration(conversionMetrics.average)}
            </Button>
        </div>
    )
}
