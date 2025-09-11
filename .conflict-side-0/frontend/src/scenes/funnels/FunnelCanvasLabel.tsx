import { useActions, useValues } from 'kea'
import React from 'react'

import { IconInfo, IconTestTube } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration, percentage } from 'lib/utils'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { getExperimentMetricFromInsight } from 'scenes/experiments/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FunnelStepsPicker } from 'scenes/insights/views/Funnels/FunnelStepsPicker'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FunnelVizType, ProductKey, type QueryBasedInsightModel } from '~/types'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { insightProps, insight, supportsCreatingExperiment, derivedName } = useValues(insightLogic)
    const { conversionMetrics, aggregationTargetLabel, funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const labels = [
        ...(funnelsFilter?.funnelVizType === FunnelVizType.Steps
            ? [
                  <>
                      <span className="flex items-center text-secondary mr-1">
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
        ...(funnelsFilter?.funnelVizType !== FunnelVizType.Trends
            ? [
                  <>
                      <span className="flex items-center text-secondary">
                          <Tooltip
                              title={`Average (arithmetic mean) of the total time each ${aggregationTargetLabel.singular} spent in the entire funnel.`}
                          >
                              <IconInfo className="mr-1 text-xl shrink-0" />
                          </Tooltip>
                          <span>Average time to convert</span>
                      </span>
                      {funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert && <FunnelStepsPicker />}
                      <span className="text-secondary mr-1">:</span>
                      {funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert ? (
                          <span className="font-bold">{humanFriendlyDuration(conversionMetrics.averageTime)}</span>
                      ) : (
                          <Link
                              className="font-bold"
                              onClick={() => updateInsightFilter({ funnelVizType: FunnelVizType.TimeToConvert })}
                          >
                              {humanFriendlyDuration(conversionMetrics.averageTime)}
                          </Link>
                      )}
                  </>,
              ]
            : []),
        ...(funnelsFilter?.funnelVizType === FunnelVizType.Trends
            ? [
                  <>
                      <span className="text-secondary">Conversion rate</span>
                      <FunnelStepsPicker />
                  </>,
              ]
            : []),

        ...(supportsCreatingExperiment
            ? [
                  <LemonButton
                      key="run-experiment"
                      icon={<IconTestTube />}
                      type="secondary"
                      data-attr="create-experiment-from-insight"
                      size="xsmall"
                      tooltip="Create a draft experiment with the metric from this funnel."
                      onClick={() =>
                          addProductIntentForCrossSell({
                              from: ProductKey.PRODUCT_ANALYTICS,
                              to: ProductKey.EXPERIMENTS,
                              intent_context: ProductIntentContext.CREATE_EXPERIMENT_FROM_FUNNEL_BUTTON,
                          })
                      }
                      to={urls.experiment('new', null, {
                          metric: getExperimentMetricFromInsight(insight as QueryBasedInsightModel),
                          name: insight.name || insight.derived_name || derivedName,
                      })}
                  >
                      Run experiment
                  </LemonButton>,
              ]
            : []),
    ]

    return (
        <div className="flex items-center">
            {labels.map((label, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span className="my-0.5 mx-2 border-l border-primary h-3.5" />}
                    {label}
                </React.Fragment>
            ))}
        </div>
    )
}
