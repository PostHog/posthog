import './Funnel.scss'
import { BindLogic, useValues } from 'kea'
import React from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FunnelBarChart } from './FunnelBarChart'

export function Funnel(props: ChartParams): JSX.Element {
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

    return (
        <BindLogic logic={funnelLogic} props={insightProps}>
            <FunnelBarChart {...props} />
        </BindLogic>
    )
}
