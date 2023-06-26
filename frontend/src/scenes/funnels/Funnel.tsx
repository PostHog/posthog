import './Funnel.scss'
import { BindLogic, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import { funnelDataLogic } from './funnelDataLogic'

import { ChartParams, FunnelVizType } from '~/types'
import { FunnelLayout } from 'lib/constants'
import { FunnelHistogramDataExploration } from './FunnelHistogram'
import { FunnelLineGraphDataExploration } from 'scenes/funnels/FunnelLineGraph'
import { FunnelBarChartDataExploration } from './FunnelBarChart/FunnelBarChart'
import { FunnelBarGraphDataExploration } from './FunnelBarGraph/FunnelBarGraph'

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { funnel_viz_type, layout } = funnelsFilter || {}

    if (funnel_viz_type == FunnelVizType.Trends) {
        return <FunnelLineGraphDataExploration {...props} />
    }

    if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        return <FunnelHistogramDataExploration />
    }

    return (
        <BindLogic logic={funnelLogic} props={insightProps}>
            {(layout || FunnelLayout.vertical) === FunnelLayout.vertical ? (
                <FunnelBarChartDataExploration {...props} />
            ) : (
                <FunnelBarGraphDataExploration {...props} />
            )}
        </BindLogic>
    )
}
