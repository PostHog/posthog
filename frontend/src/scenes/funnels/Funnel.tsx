import './Funnel.scss'
import { useValues } from 'kea'
import React from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelBarGraph } from './FunnelBarGraph'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'

export function Funnel(props: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(funnelLogic(insightProps))
    const { funnel_viz_type } = filters

    // Funnel Viz
    if (funnel_viz_type == FunnelVizType.Trends) {
        return <FunnelLineGraph {...props} />
    }

    if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        return <FunnelHistogram />
    }

    return <FunnelBarGraph {...props} />
}
