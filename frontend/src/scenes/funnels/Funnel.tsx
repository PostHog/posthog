import { useValues } from 'kea'
import React from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelBarGraph } from './FunnelBarGraph'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'

import './Funnel.scss'

export function Funnel(props: Omit<ChartParams, 'view'>): JSX.Element | null {
    const logic = funnelLogic({
        dashboardItemId: props.dashboardItemId,
        filters: props.filters,
        cachedResults: props.cachedResults,
    })
    const { filters } = useValues(logic)
    const funnel_viz_type = filters.funnel_viz_type || props.filters.funnel_viz_type

    // Funnel Viz
    if (funnel_viz_type == FunnelVizType.Trends) {
        return <FunnelLineGraph {...props} />
    }

    if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        return <FunnelHistogram {...props} />
    }

    return <FunnelBarGraph {...props} />
}
