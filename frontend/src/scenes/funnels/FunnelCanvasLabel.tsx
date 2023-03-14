import './FunnelCanvasLabel.scss'
import React from 'react'
import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import { funnelDataLogic } from './funnelDataLogic'

import { Link } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'
import { InsightFilter } from '~/queries/schema'
import { FunnelsFilterType, FunnelTimeConversionMetrics, FunnelVizType } from '~/types'
import { humanFriendlyDuration, percentage } from 'lib/utils'
import { FunnelStepsPicker, FunnelStepsPickerDataExploration } from 'scenes/insights/views/Funnels/FunnelStepsPicker'
import { Noun } from '~/models/groupsModel'

export function FunnelCanvasLabelDataExploration(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { conversionMetrics, aggregationTargetLabel, funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return (
        <FunnelCanvasLabelComponent
            conversionMetrics={conversionMetrics}
            aggregationTargetLabel={aggregationTargetLabel}
            funnelsFilter={funnelsFilter}
            updateInsightFilter={updateInsightFilter}
            isUsingDataExploration
        />
    )
}

export function FunnelCanvasLabel(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { conversionMetrics, aggregationTargetLabel, filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return (
        <FunnelCanvasLabelComponent
            conversionMetrics={conversionMetrics}
            aggregationTargetLabel={aggregationTargetLabel}
            funnelsFilter={filters}
            updateInsightFilter={(filters: InsightFilter) => {
                setFilters(filters as Partial<FunnelsFilterType>)
            }}
        />
    )
}

type FunnelCanvasLabelComponentProps = {
    aggregationTargetLabel: Noun
    conversionMetrics: FunnelTimeConversionMetrics
    funnelsFilter?: FunnelsFilterType | null
    updateInsightFilter: (insightFilter: InsightFilter) => void
    isUsingDataExploration?: boolean
}

function FunnelCanvasLabelComponent({
    aggregationTargetLabel,
    conversionMetrics,
    funnelsFilter,
    updateInsightFilter,
    isUsingDataExploration,
}: FunnelCanvasLabelComponentProps): JSX.Element | null {
    const StepsPicker = isUsingDataExploration ? FunnelStepsPickerDataExploration : FunnelStepsPicker
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
                      {funnelsFilter?.funnel_viz_type === FunnelVizType.TimeToConvert && <StepsPicker />}
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
                      <StepsPicker />
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
