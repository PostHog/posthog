import { useValues } from 'kea'
import React from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelBarGraph } from './FunnelBarGraph'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { FunnelEmptyState, FunnelInvalidFiltersEmptyState } from 'scenes/insights/EmptyStates/EmptyStates'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { Loading } from 'lib/utils'

export function Funnel(props: Omit<ChartParams, 'view'>): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const logic = funnelLogic({ dashboardItemId: props.dashboardItemId, filters: props.filters })
    const { filters, areFiltersValid, resultsLoading, isValidFunnel } = useValues(logic)
    const funnel_viz_type = filters.funnel_viz_type || props.filters.funnel_viz_type

    if (!areFiltersValid) {
        return <FunnelInvalidFiltersEmptyState />
    }
    if (resultsLoading) {
        return <Loading />
    }
    if (!isValidFunnel) {
        return <FunnelEmptyState />
    }

    if (featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ]) {
        if (funnel_viz_type == FunnelVizType.Steps || !funnel_viz_type) {
            return <FunnelBarGraph {...props} />
        }

        if (funnel_viz_type == FunnelVizType.TimeToConvert) {
            return <FunnelHistogram {...props} />
        }
    }

    if (funnel_viz_type === FunnelVizType.Trends) {
        return <FunnelLineGraph {...props} />
    }

    // TODO: Remove this line when #4785 (Nail Funnels) has been rolled out to all users
    return <FunnelViz {...props} />
}
