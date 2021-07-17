// This file contains funnel-related components that are used in the general insights scope
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { Button } from 'antd'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import './FunnelCanvasLabel.scss'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { FunnelVizType } from '~/types'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { stepsWithCount, histogramStep, totalConversionRate } = useValues(funnelLogic)
    const { allFilters } = useValues(insightLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    if (allFilters.insight !== 'FUNNELS') {
        return null
    }

    return (
        <div className="funnel-canvas-label">
            {allFilters.funnel_viz_type === FunnelVizType.Steps && (
                <>
                    <span className="text-muted-alt">Total conversion rate: </span>
                    <span>{totalConversionRate}%</span>
                    <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />
                </>
            )}
            <span className="text-muted-alt">Average time to convert: </span>
            <Button
                type="link"
                disabled={allFilters.funnel_viz_type === FunnelVizType.TimeToConvert}
                onClick={() => setChartFilter(FunnelVizType.TimeToConvert)}
            >
                {humanFriendlyDuration(stepsWithCount[histogramStep]?.average_conversion_time)}
            </Button>
        </div>
    )
}
