// This file contains funnel-related components that are used in the general insights scope
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { Button, Tooltip } from 'antd'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import './FunnelCanvasLabel.scss'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { ChartDisplayType } from '~/types'
import { InfoCircleOutlined } from '@ant-design/icons'

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
                    <span className="text-muted-alt">
                        <Tooltip title="This is calculated by taking the sum of durations users spent in the defined funnel.">
                            <InfoCircleOutlined style={{ marginRight: 3 }} />
                            Total conversion rate:{' '}
                        </Tooltip>
                    </span>
                    <span>{conversionMetrics.totalRate}%</span>
                    <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />
                </>
            )}
            <span className="text-muted-alt">
                <Tooltip title="This is calculated by taking the mean of durations users spent in the defined funnel.">
                    <InfoCircleOutlined style={{ marginRight: 3 }} />
                    Average time to convert:{' '}
                </Tooltip>
            </span>
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
