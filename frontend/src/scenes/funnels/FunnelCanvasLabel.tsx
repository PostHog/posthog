import './FunnelCanvasLabel.scss'
import React from 'react'
import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from './funnelDataLogic'

import { Link } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'
import { FunnelVizType } from '~/types'
import { humanFriendlyDuration, percentage } from 'lib/utils'
import { FunnelStepsPicker } from 'scenes/insights/views/Funnels/FunnelStepsPicker'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { conversionMetrics, aggregationTargetLabel, funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const labels = [
        ...(funnelsFilter?.funnel_viz_type === FunnelVizType.Steps
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
        ...(funnelsFilter?.funnel_viz_type !== FunnelVizType.Trends
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
                      {funnelsFilter?.funnel_viz_type === FunnelVizType.TimeToConvert && <FunnelStepsPicker />}
                      <span className="text-muted-alt mr-1">:</span>
                      {funnelsFilter?.funnel_viz_type === FunnelVizType.TimeToConvert ? (
                          <span className="font-bold">{humanFriendlyDuration(conversionMetrics.averageTime)}</span>
                      ) : (
                          <Link
                              className="font-bold"
                              onClick={() => updateInsightFilter({ funnel_viz_type: FunnelVizType.TimeToConvert })}
                          >
                              {humanFriendlyDuration(conversionMetrics.averageTime)}
                          </Link>
                      )}
                  </>,
              ]
            : []),
        ...(funnelsFilter?.funnel_viz_type === FunnelVizType.Trends
            ? [
                  <>
                      <span className="text-muted-alt">Conversion rate</span>
                      <FunnelStepsPicker />
                  </>,
              ]
            : []),
    ]

    return (
        <div className="flex items-center">
            {labels.map((label, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span className="my-0.5 mx-2 border-l border-border h-3.5" />}
                    {label}
                </React.Fragment>
            ))}
        </div>
    )
}
