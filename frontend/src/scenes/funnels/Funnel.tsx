import './Funnel.scss'

import { useValues } from 'kea'

import { FunnelLayout } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams, FunnelVizType } from '~/types'

import { FunnelBarHorizontalChart } from 'products/product_analytics/frontend/insights/funnels/FunnelBarHorizontalChart/FunnelBarHorizontalChart'
import { FunnelHistogramChart } from 'products/product_analytics/frontend/insights/funnels/FunnelHistogramChart/FunnelHistogramChart'
import { FunnelLineChart } from 'products/product_analytics/frontend/insights/funnels/FunnelLineChart/FunnelLineChart'
import { FunnelStepsBarChart } from 'products/product_analytics/frontend/insights/funnels/FunnelStepsBarChart/FunnelStepsBarChart'

import { funnelDataLogic } from './funnelDataLogic'
import { FunnelFlowGraph } from './FunnelFlowGraph/FunnelFlowGraph'

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { funnelVizType, layout } = funnelsFilter || {}

    let viz: JSX.Element | null = null
    if (funnelVizType == FunnelVizType.Trends) {
        viz = <FunnelLineChart {...props} />
    } else if (funnelVizType == FunnelVizType.TimeToConvert) {
        viz = <FunnelHistogramChart />
    } else if (funnelVizType === FunnelVizType.Flow) {
        viz = <FunnelFlowGraph />
    } else if ((layout || FunnelLayout.vertical) === FunnelLayout.vertical) {
        viz = <FunnelStepsBarChart {...props} />
    } else {
        viz = <FunnelBarHorizontalChart {...props} />
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
