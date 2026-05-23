import './Funnel.scss'

import { useValues } from 'kea'
import { lazy, Suspense } from 'react'

import { FunnelLayout } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams, FunnelVizType } from '~/types'

import { FunnelBarHorizontal } from './FunnelBarHorizontal/FunnelBarHorizontal'
import { FunnelBarVertical } from './FunnelBarVertical/FunnelBarVertical'
import { funnelDataLogic } from './funnelDataLogic'
import { FunnelFlowGraph } from './FunnelFlowGraph/FunnelFlowGraph'
import { FunnelHistogram } from './FunnelHistogram'

// Flag-gated — keep the hog-charts viz bundles out of the eager Funnel/Dashboard bundle
const FunnelHistogramChart = lazy(() =>
    import('products/product_analytics/frontend/insights/funnels/FunnelHistogramChart/FunnelHistogramChart').then(
        (m) => ({ default: m.FunnelHistogramChart })
    )
)
const FunnelLineChart = lazy(() =>
    import('products/product_analytics/frontend/insights/funnels/FunnelLineChart/FunnelLineChart').then((m) => ({
        default: m.FunnelLineChart,
    }))
)
const FunnelStepsBarChart = lazy(() =>
    import('products/product_analytics/frontend/insights/funnels/FunnelStepsBarChart/FunnelStepsBarChart').then(
        (m) => ({ default: m.FunnelStepsBarChart })
    )
)

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
            <Suspense
                fallback={
                    <WrappingLoadingSkeleton fullWidth>
                        <span className="block w-full h-72" />
                    </WrappingLoadingSkeleton>
                }
            >
                {viz}
            </Suspense>
        </div>
    )
}
