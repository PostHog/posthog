import './Funnel.scss'

import { clsx } from 'clsx'
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

    const isStepsVertical =
        funnelVizType === FunnelVizType.Steps && (layout ?? FunnelLayout.vertical) === FunnelLayout.vertical

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
            className={clsx(
                'FunnelInsight',
                `FunnelInsight--type-${funnelVizType?.toLowerCase()}${
                    funnelVizType === FunnelVizType.Steps ? '-' + (layout ?? FunnelLayout.vertical) : ''
                }`,
                // The quill FunnelChart needs a definite parent height to fill; a flex-derived /
                // min-height-only size doesn't count. Pin the height on the main insight view
                // (min-height comes from InsightViz.scss), resetting to auto wherever the funnel is
                // embedded — same reason .TrendsInsight pins one.
                isStepsVertical && [
                    'h-[var(--insight-viz-min-height)] max-h-[var(--insight-viz-min-height)]',
                    '[.NotebookNode_&]:h-auto [.NotebookNode_&]:max-h-none',
                    '[.InsightCard_&]:h-auto [.InsightCard_&]:max-h-none',
                    '[.ExportedInsight_&]:h-auto [.ExportedInsight_&]:max-h-none',
                    '[.WebAnalyticsDashboard_&]:h-auto [.WebAnalyticsDashboard_&]:max-h-none',
                ]
            )}
        >
            {viz}
        </div>
    )
}
