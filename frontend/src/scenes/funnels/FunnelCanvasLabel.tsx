// This file contains funnel-related components that are used in the general insights scope
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { Button, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import './FunnelCanvasLabel.scss'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { FunnelVizType } from '~/types'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { stepsWithCount, histogramStep, conversionMetrics, clickhouseFeaturesEnabled } = useValues(funnelLogic)
    const { allFilters } = useValues(insightLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    if (allFilters.insight !== 'FUNNELS') {
        return null
    }

    return (
        <div className="funnel-canvas-label">
            {allFilters.funnel_viz_type === FunnelVizType.Steps && (
                <>
                    <span className="text-muted-alt">
                        <Tooltip title="Overall conversion rate for all users on the entire funnel.">
                            <InfoCircleOutlined style={{ marginRight: 3 }} />
                        </Tooltip>
                        Total conversion rate:{' '}
                    </span>
                    <span>{conversionMetrics.totalRate}%</span>
                    <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />
                </>
            )}
            {stepsWithCount[histogramStep.from_step]?.average_conversion_time !== null && (
                <>
                    <span className="text-muted-alt">
                        <Tooltip title="Average (arithmetic mean) of the total time each user spent in the enitre funnel.">
                            <InfoCircleOutlined style={{ marginRight: 3 }} />
                        </Tooltip>
                        Average time to convert:{' '}
                    </span>
                    <Button
                        type="link"
                        onClick={() => setChartFilter(FunnelVizType.TimeToConvert)}
                        disabled={
                            !clickhouseFeaturesEnabled || allFilters.funnel_viz_type === FunnelVizType.TimeToConvert
                        }
                    >
                        {humanFriendlyDuration(conversionMetrics.averageTime)}
                    </Button>
                </>
            )}
        </div>
    )
}
