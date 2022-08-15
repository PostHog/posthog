import './Funnel.scss'
import { BindLogic, useValues } from 'kea'
import React from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FunnelLayout } from 'lib/constants'
import { FunnelBarChart } from './FunnelBarChart'
import { FunnelBarGraph } from './FunnelBarGraph'

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters, barGraphLayout } = useValues(funnelLogic(insightProps))
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
            {barGraphLayout === FunnelLayout.vertical ? <FunnelBarChart {...props} /> : <FunnelBarGraph {...props} />}
        </BindLogic>
    )
}
