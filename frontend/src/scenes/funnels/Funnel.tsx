import './Funnel.scss'
import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from './funnelDataLogic'

import { ChartParams, FunnelVizType } from '~/types'
import { FunnelLayout } from 'lib/constants'
import { FunnelHistogram } from './FunnelHistogram'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { FunnelBarChart } from './FunnelBarChart/FunnelBarChart'
import { FunnelBarGraph } from './FunnelBarGraph/FunnelBarGraph'

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { funnel_viz_type, layout } = funnelsFilter || {}

    let viz: JSX.Element | null = null
    if (funnel_viz_type == FunnelVizType.Trends) {
        viz = <FunnelLineGraph {...props} />
    } else if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        viz = <FunnelHistogram />
    } else if ((layout || FunnelLayout.vertical) === FunnelLayout.vertical) {
        viz = <FunnelBarChart {...props} />
    } else {
        viz = <FunnelBarGraph {...props} />
    }

    return (
        <div
            className={`FunnelInsight FunnelInsight--type-${funnel_viz_type?.toLowerCase()}${
                funnel_viz_type === FunnelVizType.Steps ? '-' + (layout ?? FunnelLayout.vertical) : ''
            }`}
        >
            {viz}
        </div>
    )
}
