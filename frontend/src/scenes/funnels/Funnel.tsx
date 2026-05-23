import './Funnel.scss'

import { useValues } from 'kea'

import { FunnelLayout } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams, FunnelVizType } from '~/types'

import { FunnelHistogramChart } from 'products/product_analytics/frontend/insights/funnels/FunnelHistogramChart/FunnelHistogramChart'
import { FunnelLineChart } from 'products/product_analytics/frontend/insights/funnels/FunnelLineChart/FunnelLineChart'
import { FunnelStepsBarChart } from 'products/product_analytics/frontend/insights/funnels/FunnelStepsBarChart/FunnelStepsBarChart'

import { FunnelBarHorizontal } from './FunnelBarHorizontal/FunnelBarHorizontal'
import { FunnelBarVertical } from './FunnelBarVertical/FunnelBarVertical'
import { funnelDataLogic } from './funnelDataLogic'
import { FunnelFlowGraph } from './FunnelFlowGraph/FunnelFlowGraph'
import { FunnelHistogram } from './FunnelHistogram'

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const hogChartsFunnelEnabled = useFeatureFlag('PRODUCT_ANALYTICS_HOG_CHARTS_FUNNEL')
    const { funnelVizType, layout } = funnelsFilter || {}

    let viz: JSX.Element | null = null
    if (funnelVizType == FunnelVizType.Trends) {
        viz = hogChartsFunnelEnabled ? <FunnelLineChart {...props} /> : <FunnelLineGraph {...props} />
    } else if (funnelVizType == FunnelVizType.TimeToConvert) {
        viz = hogChartsFunnelEnabled ? <FunnelHistogramChart /> : <FunnelHistogram />
    } else if (funnelVizType === FunnelVizType.Flow) {
        viz = <FunnelFlowGraph />
    } else if ((layout || FunnelLayout.vertical) === FunnelLayout.vertical) {
        viz = hogChartsFunnelEnabled ? <FunnelStepsBarChart {...props} /> : <FunnelBarVertical {...props} />
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
