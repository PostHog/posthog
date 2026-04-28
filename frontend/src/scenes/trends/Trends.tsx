import { useActions, useValues } from 'kea'
import { Suspense, lazy } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, InsightType } from '~/types'

import { trendsDataLogic } from './trendsDataLogic'
import { ActionsHorizontalBar, ActionsLineGraph, ActionsPie } from './viz'
// Lazy-loaded viz types that are rarely used on dashboards
const WorldMap = lazy(() => import('scenes/insights/views/WorldMap').then((m) => ({ default: m.WorldMap })))
const RegionMap = lazy(() => import('scenes/insights/views/RegionMap').then((m) => ({ default: m.RegionMap })))
const TrendsCalendarHeatMap = lazy(() =>
    import('scenes/insights/views/CalendarHeatMap').then((m) => ({ default: m.TrendsCalendarHeatMap }))
)
const BoxPlotChart = lazy(() => import('scenes/insights/views/BoxPlot').then((m) => ({ default: m.BoxPlotChart })))
// Flag-gated — keep full d3 out of the eager Trends/Dashboard bundle
const TrendsLineChart = lazy(() => import('./viz/TrendsLineChart').then((m) => ({ default: m.TrendsLineChart })))

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
    const { featureFlags } = useValues(featureFlagLogic)

    const { display, series, breakdownFilter, hasBreakdownMore, breakdownValuesLoading } = useValues(
        trendsDataLogic(insightProps)
    )
    const { updateBreakdownFilter } = useActions(trendsDataLogic(insightProps))

    const commonProps = {
        showPersonsModal,
        context,
        inCardView: embedded && !inSharedMode,
        inSharedMode,
    }

    const renderViz = (): JSX.Element | undefined => {
        if (
            !display ||
            display === ChartDisplayType.ActionsLineGraph ||
            display === ChartDisplayType.ActionsLineGraphCumulative ||
            display === ChartDisplayType.ActionsAreaGraph
        ) {
            if (featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS]) {
                return <TrendsLineChart context={context} inSharedMode={inSharedMode} />
            }
            return <ActionsLineGraph {...commonProps} />
        }
        if (display === ChartDisplayType.ActionsBar || display === ChartDisplayType.ActionsUnstackedBar) {
            return <ActionsLineGraph {...commonProps} />
        }
        if (display === ChartDisplayType.BoldNumber) {
            return <BoldNumber {...commonProps} />
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
            return <ActionsPie {...commonProps} />
        }
        if (display === ChartDisplayType.ActionsBarValue) {
            return <ActionsHorizontalBar {...commonProps} />
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
    }

    return (
        <>
            {series && (
                <div className={embedded ? 'InsightCard__viz' : `TrendsInsight TrendsInsight--${display}`}>
                    <Suspense fallback={null}>{renderViz()}</Suspense>
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
