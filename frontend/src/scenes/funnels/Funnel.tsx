import './Funnel.scss'
import { BindLogic, useValues } from 'kea'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelHistogram, FunnelHistogramDataExploration } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FunnelLayout } from 'lib/constants'
import { FunnelBarChart, FunnelBarChartDataExploration } from './FunnelBarChart/FunnelBarChart'
import { FunnelBarGraph } from './FunnelBarGraph'
import { funnelDataLogic } from './funnelDataLogic'

export function FunnelDataExploration(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { funnel_viz_type, layout } = funnelsFilter || {}

    if (funnel_viz_type == FunnelVizType.Trends) {
        return <FunnelLineGraph {...props} />
    }

    if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        return <FunnelHistogramDataExploration />
    }

    return (
        <BindLogic logic={funnelLogic} props={insightProps}>
            {(layout || FunnelLayout.vertical) === FunnelLayout.vertical ? (
                <FunnelBarChartDataExploration {...props} />
            ) : (
                <FunnelBarGraph {...props} />
            )}
        </BindLogic>
    )
}

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(funnelLogic(insightProps))
    const { funnel_viz_type, layout } = filters

    if (funnel_viz_type == FunnelVizType.Trends) {
        return <FunnelLineGraph {...props} />
    }

    if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        return <FunnelHistogram />
    }

    return (
        <BindLogic logic={funnelLogic} props={insightProps}>
            {(layout || FunnelLayout.vertical) === FunnelLayout.vertical ? (
                <FunnelBarChart {...props} />
            ) : (
                <FunnelBarGraph {...props} />
            )}
        </BindLogic>
    )
}
