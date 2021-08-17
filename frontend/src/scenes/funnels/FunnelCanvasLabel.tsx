// This file contains funnel-related components that are used in the general insights scope
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import React from 'react'
import { Button } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import './FunnelCanvasLabel.scss'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { FunnelVizType } from '~/types'
import { formatDisplayPercentage } from './funnelUtils'
import { Tooltip } from 'lib/components/Tooltip'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { conversionMetrics, clickhouseFeaturesEnabled } = useValues(funnelLogic)
    const { allFilters } = useValues(insightLogic)
    const { setChartFilter } = useActions(chartFilterLogic)

    if (allFilters.insight !== 'FUNNELS') {
        return null
    }

    const labels = [
        ...(allFilters.funnel_viz_type === FunnelVizType.Steps
            ? [
                  <>
                      <span className="text-muted-alt">
                          <Tooltip title="Overall conversion rate for all users on the entire funnel.">
                              <InfoCircleOutlined className="info-indicator left" />
                          </Tooltip>
                          Total conversion rate:{' '}
                      </span>
                      <span>{formatDisplayPercentage(conversionMetrics.totalRate)}%</span>
                  </>,
              ]
            : []),
        ...(allFilters.funnel_viz_type !== FunnelVizType.Trends && !allFilters.breakdown
            ? [
                  <>
                      <span className="text-muted-alt">
                          <Tooltip title="Average (arithmetic mean) of the total time each user spent in the entire funnel.">
                              <InfoCircleOutlined className="info-indicator left" />
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
                  </>,
              ]
            : []),
    ]

    return (
        <div className="funnel-canvas-label">
            {labels.map((label, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)' }} />}
                    {label}
                </React.Fragment>
            ))}
        </div>
    )
}
