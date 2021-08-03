import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelBarGraph } from './FunnelBarGraph'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { FunnelInvalidFiltersEmptyState } from 'scenes/insights/EmptyStates/EmptyStates'

export function Funnel(props: Omit<ChartParams, 'view'>): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const logic = funnelLogic({ dashboardItemId: props.dashboardItemId, filters: props.filters })
    const { filters, areFiltersValid } = useValues(logic)
    const { loadResults } = useActions(logic)

    useEffect(() => {
        loadResults()
    }, [])

    if (!areFiltersValid) {
        return <FunnelInvalidFiltersEmptyState />
    }

    if (featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ]) {
        const funnel_viz_type = filters.funnel_viz_type || props.filters.funnel_viz_type

        if (funnel_viz_type == FunnelVizType.TimeToConvert) {
            return <FunnelHistogram {...props} />
        }
        if (funnel_viz_type == FunnelVizType.Steps || !funnel_viz_type) {
            return <FunnelBarGraph {...props} />
        }
    }

    return <FunnelViz {...props} />
}
