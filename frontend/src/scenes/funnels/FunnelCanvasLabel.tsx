// This file contains funnel-related components that are used in the general insights scope
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration, percentage } from 'lib/utils'
import { Button, Row } from 'antd'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import './FunnelCanvasLabel.scss'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { FunnelVizType, InsightType } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'
import { FunnelStepsPicker } from 'scenes/insights/views/Funnels/FunnelStepsPicker'
import React from 'react'
import { IconInfo } from 'lib/components/icons'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { insightProps, activeView } = useValues(insightLogic)
    const { conversionMetrics, filters, aggregationTargetLabel } = useValues(funnelLogic(insightProps))
    const { setChartFilter } = useActions(chartFilterLogic(insightProps))

    if (activeView !== InsightType.FUNNELS) {
        return null
    }

    const labels = [
        ...(filters.funnel_viz_type === FunnelVizType.Steps
            ? [
                  <>
                      <span className="flex items-center text-muted-alt mr-1">
                          <Tooltip
                              title={`Overall conversion rate for all ${aggregationTargetLabel.plural} on the entire funnel.`}
                          >
                              <IconInfo className="mr-1 text-xl shrink-0" />
                          </Tooltip>
                          <span>Total conversion rate:</span>
                      </span>
                      <span className="l4">{percentage(conversionMetrics.totalRate, 2, true)}</span>
                  </>,
              ]
            : []),
        ...(filters.funnel_viz_type !== FunnelVizType.Trends
            ? [
                  <>
                      <span className="flex items-center text-muted-alt">
                          <Tooltip
                              title={`Average (arithmetic mean) of the total time each ${aggregationTargetLabel.singular} spent in the entire funnel.`}
                          >
                              <IconInfo className="mr-1 text-xl shrink-0" />
                          </Tooltip>
                          <span>Average time to convert</span>
                      </span>
                      {filters.funnel_viz_type === FunnelVizType.TimeToConvert && <FunnelStepsPicker />}
                      <span className="text-muted-alt mr-1">:</span>
                      <Button
                          type="link"
                          onClick={() => setChartFilter(FunnelVizType.TimeToConvert)}
                          disabled={filters.funnel_viz_type === FunnelVizType.TimeToConvert}
                      >
                          <span className="l4">{humanFriendlyDuration(conversionMetrics.averageTime)}</span>
                      </Button>
                  </>,
              ]
            : []),
        ...(filters.funnel_viz_type === FunnelVizType.Trends
            ? [
                  <>
                      <span className="text-muted-alt">Conversion rate </span>
                      <FunnelStepsPicker />
                  </>,
              ]
            : []),
    ]

    return (
        <Row className="funnel-canvas-label" align="middle">
            {labels.map((label, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span style={{ margin: '2px 8px', borderLeft: '1px solid var(--border)', height: 14 }} />}
                    {label}
                </React.Fragment>
            ))}
        </Row>
    )
}
