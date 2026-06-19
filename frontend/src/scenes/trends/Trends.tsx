import { useActions, useValues } from 'kea'
import { Suspense, lazy } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { insightLogic } from 'scenes/insights/insightLogic'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { Metric } from 'scenes/insights/views/Metric/Metric'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, InsightType } from '~/types'

import { trendsDataLogic } from './trendsDataLogic'
// Lazy-loaded viz types that are rarely used on dashboards
const WorldMap = lazy(() => import('scenes/insights/views/WorldMap').then((m) => ({ default: m.WorldMap })))
const RegionMap = lazy(() => import('scenes/insights/views/RegionMap').then((m) => ({ default: m.RegionMap })))
const TrendsCalendarHeatMap = lazy(() =>
    import('scenes/insights/views/CalendarHeatMap').then((m) => ({ default: m.TrendsCalendarHeatMap }))
)
const BoxPlotChart = lazy(() => import('scenes/insights/views/BoxPlot').then((m) => ({ default: m.BoxPlotChart })))
// Lazy-loaded — keep the quill/d3 slope chart out of the eager Trends/Dashboard bundle
const TrendsSlopeChart = lazy(() =>
    import('products/product_analytics/frontend/insights/trends/TrendsSlopeChart/TrendsSlopeChart').then((m) => ({
        default: m.TrendsSlopeChart,
    }))
)
// Lazy-loaded — keep full d3 out of the eager Trends/Dashboard bundle
const TrendsLineChart = lazy(() =>
    import('products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChart').then((m) => ({
        default: m.TrendsLineChart,
    }))
)
const TrendsBarChart = lazy(() =>
    import('products/product_analytics/frontend/insights/trends/TrendsBarChart/TrendsBarChart').then((m) => ({
        default: m.TrendsBarChart,
    }))
)
const StickinessLineChart = lazy(() =>
    import('products/product_analytics/frontend/insights/stickiness/StickinessLineChart/StickinessLineChart').then(
        (m) => ({
            default: m.StickinessLineChart,
        })
    )
)
const StickinessBarChart = lazy(() =>
    import('products/product_analytics/frontend/insights/stickiness/StickinessBarChart/StickinessBarChart').then(
        (m) => ({
            default: m.StickinessBarChart,
        })
    )
)
const TrendsPieChart = lazy(() =>
    import('products/product_analytics/frontend/insights/trends/TrendsPieChart/TrendsPieChart').then((m) => ({
        default: m.TrendsPieChart,
    }))
)
const TrendsLifecycleChart = lazy(() =>
    import('products/product_analytics/frontend/insights/trends/TrendsLifecycleChart/TrendsLifecycleChart').then(
        (m) => ({
            default: m.TrendsLifecycleChart,
        })
    )
)

interface Props {
    view: InsightType
    context?: QueryContext<InsightVizNode>
    embedded?: boolean
    inSharedMode?: boolean
    editMode?: boolean
}

export function TrendInsight({ view, context, embedded, inSharedMode, editMode }: Props): JSX.Element {
    const { insightProps, showPersonsModal: insightLogicShowPersonsModal } = useValues(insightLogic)
    const showPersonsModal = insightLogicShowPersonsModal && !inSharedMode

    const { display, series, breakdownFilter, hasBreakdownMore, breakdownValuesLoading, isLifecycle, isStickiness } =
        useValues(trendsDataLogic(insightProps))
    const { updateBreakdownFilter } = useActions(trendsDataLogic(insightProps))

    const commonProps = {
        showPersonsModal,
        context,
        inCardView: embedded && !inSharedMode,
        inSharedMode,
    }

    const renderViz = (): JSX.Element | undefined => {
        if (isLifecycle) {
            return <TrendsLifecycleChart context={context} inSharedMode={inSharedMode} />
        }
        if (
            !display ||
            display === ChartDisplayType.ActionsLineGraph ||
            display === ChartDisplayType.ActionsLineGraphCumulative ||
            display === ChartDisplayType.ActionsAreaGraph
        ) {
            if (isStickiness) {
                return <StickinessLineChart context={context} />
            }
            return <TrendsLineChart context={context} inSharedMode={inSharedMode} />
        }
        if (display === ChartDisplayType.ActionsBar || display === ChartDisplayType.ActionsUnstackedBar) {
            if (isStickiness) {
                return <StickinessBarChart context={context} />
            }
            return <TrendsBarChart context={context} inSharedMode={inSharedMode} embedded={embedded} />
        }
        if (display === ChartDisplayType.BoldNumber) {
            return <BoldNumber {...commonProps} />
        }
        if (display === ChartDisplayType.Metric) {
            return <Metric {...commonProps} />
        }
        if (display === ChartDisplayType.ActionsTable) {
            return (
                <InsightsTable
                    embedded
                    filterKey={`trends_${view}`}
                    canEditSeriesNameInline={editMode}
                    editMode={editMode}
                    isMainInsightView={true}
                />
            )
        }
        if (display === ChartDisplayType.ActionsPie) {
            return <TrendsPieChart context={context} inSharedMode={inSharedMode} showPersonsModal={showPersonsModal} />
        }
        if (display === ChartDisplayType.ActionsBarValue) {
            return <TrendsBarChart context={context} inSharedMode={inSharedMode} embedded={embedded} />
        }
        if (display === ChartDisplayType.WorldMap) {
            const hasSubdivisionBreakdown =
                breakdownFilter?.breakdowns &&
                breakdownFilter.breakdowns.length >= 2 &&
                breakdownFilter.breakdowns.some(
                    (b) => b.property === '$geoip_subdivision_1_code' || b.property === '$geoip_subdivision_1_name'
                )

            if (hasSubdivisionBreakdown) {
                return <RegionMap {...commonProps} />
            }

            return <WorldMap {...commonProps} />
        }
        if (display === ChartDisplayType.CalendarHeatmap) {
            return <TrendsCalendarHeatMap {...commonProps} />
        }
        if (display === ChartDisplayType.BoxPlot) {
            return <BoxPlotChart {...commonProps} inCardView={embedded} />
        }
        if (display === ChartDisplayType.SlopeGraph) {
            return <TrendsSlopeChart context={context} />
        }
    }

    return (
        <>
            {series && (
                <div className={embedded ? 'InsightCard__viz' : `TrendsInsight TrendsInsight--${display}`}>
                    <Suspense
                        fallback={
                            <WrappingLoadingSkeleton fullWidth>
                                <span className="block w-full h-72" />
                            </WrappingLoadingSkeleton>
                        }
                    >
                        {renderViz()}
                    </Suspense>
                </div>
            )}
            {!embedded &&
                display !== ChartDisplayType.WorldMap && // the world map doesn't need this cta
                display !== ChartDisplayType.CalendarHeatmap && // the heatmap doesn't need this cta
                display !== ChartDisplayType.BoxPlot && // box plot doesn't support breakdowns
                breakdownFilter &&
                hasBreakdownMore && (
                    <div className="p-4">
                        <div className="text-secondary">
                            Breakdown limited to {breakdownFilter.breakdown_limit || 25} - more available
                            <LemonButton
                                onClick={() =>
                                    updateBreakdownFilter({
                                        ...breakdownFilter,
                                        breakdown_limit: (breakdownFilter.breakdown_limit || 25) * 2,
                                    })
                                }
                                loading={breakdownValuesLoading}
                                size="xsmall"
                                type="secondary"
                                className="inline-block ml-2"
                            >
                                Set to {(breakdownFilter.breakdown_limit || 25) * 2}
                            </LemonButton>
                        </div>
                    </div>
                )}
        </>
    )
}
