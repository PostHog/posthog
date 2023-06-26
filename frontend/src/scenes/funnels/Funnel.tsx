import './Funnel.scss'
import { BindLogic, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
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
