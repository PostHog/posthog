import './Funnel.scss'

import { useValues } from 'kea'

import { FunnelLayout } from 'lib/constants'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams, FunnelVizType } from '~/types'

import { FunnelBarHorizontal } from './FunnelBarHorizontal/FunnelBarHorizontal'
import { FunnelBarVertical } from './FunnelBarVertical/FunnelBarVertical'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelDataLogic } from './funnelDataLogic'

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { funnelVizType, layout } = funnelsFilter || {}

    let viz: JSX.Element | null = null
    if (funnelVizType == FunnelVizType.Trends) {
        viz = <FunnelLineGraph {...props} />
    } else if (funnelVizType == FunnelVizType.TimeToConvert) {
        viz = <FunnelHistogram />
    } else if ((layout || FunnelLayout.vertical) === FunnelLayout.vertical) {
        viz = <FunnelBarVertical {...props} />
    } else {
        viz = <FunnelBarHorizontal {...props} />
    }

    return (
        <div
            className={`FunnelInsight FunnelInsight--type-${funnelVizType?.toLowerCase()}${
                funnelVizType === FunnelVizType.Steps ? '-' + (layout ?? FunnelLayout.vertical) : ''
            }`}
        >
            {viz}
        </div>
    )
}
