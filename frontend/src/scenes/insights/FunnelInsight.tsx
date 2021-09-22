import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { FunnelVizType } from '~/types'

export function FunnelInsight(): JSX.Element {
    const { isValidFunnel, isLoading, filters, areFiltersValid } = useValues(funnelLogic({}))
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state': (isValidFunnel && areFiltersValid) || isLoading,
                'no-padding':
                    featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN] &&
                    filters.funnel_viz_type == FunnelVizType.Steps,
            })}
        >
            <Funnel filters={{ funnel_viz_type: filters.funnel_viz_type }} />
        </div>
    )
}
