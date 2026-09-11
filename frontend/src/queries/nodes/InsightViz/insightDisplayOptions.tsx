import { useValues } from 'kea'

import { normalizeAxisLabel } from '@posthog/quill-charts'

import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { PIE_DISPLAY_TYPES } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import type { TrendsFilter } from '~/queries/schema/schema-general'
import { hasBreakdownFilter } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'

import { DisplayOption, DisplayOptions } from './DisplayOptions'
import { BAR_DISPLAYS, displayMatches, isDefaultTrendsLineDisplay, LINE_DISPLAYS } from './displayTypes'

export interface DisplayOptionSection {
    key: string
    title?: string
    tooltip?: string
    dataAttr?: string
    items: DisplayOption[]
}

export type DisplayOptionTabKey = 'general' | 'axes' | 'lines'

export interface DisplayOptionTab {
    key: DisplayOptionTabKey
    label: string
    sections: DisplayOptionSection[]
    count: number
}

function countTruthy(...flags: (boolean | null | undefined)[]): number {
    return flags.filter(Boolean).length
}

// The "Options" panel in the insight editor's display config bar. `count` is the total number of
// non-default active options across all tabs, badged on the Options button.
export function useInsightDisplayOptions(): { tabs: DisplayOptionTab[]; count: number } {
    const { insightProps } = useValues(insightLogic)
    const {
        querySource,
        isTrends,
        isRetention,
        isStickiness,
        isLifecycle,
        display,
        breakdownFilter,
        trendsFilter,
        hasLegend,
        showLegend,
        supportsValueOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        supportsBarValueStacking,
        supportsResultCustomizationBy,
        yAxisScaleType,
        showMultipleYAxes,
        showAlertThresholdLines,
        showAnnotations,
        isNonTimeSeriesDisplay,
        interval,
        usesInChartLegend,
        insightFilter,
    } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const {
        showValuesOnSeries,
        showPercentagesOnSeries,
        mightContainFractionalNumbers,
        showConfidenceIntervals,
        showMovingAverage,
    } = useValues(trendsDataLogic(insightProps))

    // The slope graph shows the first vs last interval, so it drops the options that need the points
    // between them (smoothing, multiple axes, alert/annotation overlays, statistical analysis).
    const isSlopeGraph = display === ChartDisplayType.SlopeGraph
    const isMetric = display === ChartDisplayType.Metric
    const isBoxPlot = display === ChartDisplayType.BoxPlot
    const hideContinuousChartOptions = isNonTimeSeriesDisplay || isMetric || isSlopeGraph
    const showSmoothing =
        isTrends &&
        !hasBreakdownFilter(breakdownFilter) &&
        (!display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph) &&
        !!interval &&
        (smoothingOptions[interval]?.length ?? 0) > 0
    const showMultipleYAxesConfig = (isTrends || isStickiness) && !hideContinuousChartOptions && !isBoxPlot
    const showAlertThresholdLinesConfig = isTrends && !hideContinuousChartOptions
    const showAnnotationsConfig = (isTrends && !hideContinuousChartOptions) || isTrendsFunnel
    const showTrendLinesConfig = (isTrends || isRetention || isTrendsFunnel) && !hideContinuousChartOptions
    // Stickiness defaults to its line chart when display is unset, same as trends does — but
    // isDefaultTrendsLineDisplay only matches TrendsQuery, so we handle the stickiness case here.
    const isLineDisplay =
        isDefaultTrendsLineDisplay(display, querySource) ||
        displayMatches(display, LINE_DISPLAYS) ||
        (!display && isStickiness)
    const isBarDisplay = displayMatches(display, BAR_DISPLAYS)
    const showAxisLabelsConfig = isTrends && (isLineDisplay || isBarDisplay)
    const showFunnelLegendConfig = isTrendsFunnel && hasBreakdownFilter(breakdownFilter)
    const isCalendarHeatmap = display === ChartDisplayType.CalendarHeatmap
    const isPie = !!display && PIE_DISPLAY_TYPES.includes(display)
    // Percent stacking swaps the raw values out for percentages, so there is no unit left to pick.
    // A pie is the exception: it can show the value and the percentage together.
    const showsRawValues = !showPercentStackView || (isPie && !!showValuesOnSeries)
    // When the chart draws its own positioned in-chart legend, show the position selector instead
    // of the legacy show/hide checkbox. usesInChartLegend is the single source of truth (same
    // selector used by InsightVizDisplay to suppress the side legend). Funnel trends with breakdown
    // also get the position selector since they render the quill legend via config.legend.
    const useQuillLegendOptions = usesInChartLegend || showFunnelLegendConfig

    const showDisplaySection =
        (isTrends && !isCalendarHeatmap) || isRetention || isTrendsFunnel || isStickiness || isLifecycle
    const showYAxisScale = !hideContinuousChartOptions && isTrends && !isCalendarHeatmap
    // Bars encode magnitude as length from zero, so a bounded baseline misreads them: 10 vs 11
    // would draw as 1 vs 2.
    const showYAxisRangeConfig = showYAxisScale && isLineDisplay
    // Only the quill line charts (trends/stickiness line and area, retention and funnel-trends
    // graphs) draw curves, so they're the only ones with curvature to straighten. Retention and
    // funnel trends default to their line graph when display is unset.
    const isLineChartInsight = isLineDisplay || ((isRetention || isTrendsFunnel) && !display)
    const showLineStyleConfig = (isTrends || isStickiness || isRetention || isTrendsFunnel) && isLineChartInsight
    const showStatisticalOverlays = showYAxisScale && !isBoxPlot
    const showUnit = showsRawValues && isTrends && !isCalendarHeatmap
    const showDecimalPlaces = mightContainFractionalNumbers && isTrends && !isCalendarHeatmap

    // The box plot and slope graph only show a couple of options each; everything else falls
    // through to the full shared list.
    const getDisplayItems = (): DisplayOption[] => {
        const displayItems: DisplayOption[] = []

        if (isBoxPlot) {
            if (hasLegend) {
                displayItems.push(DisplayOptions.Legend)
            }
            displayItems.push(DisplayOptions.ExcludeOutliers)
            return displayItems
        }

        if (isSlopeGraph) {
            // A slope only shows the first vs last interval of each series — the legend (when there
            // are multiple series) is the only display option that applies.
            if (hasLegend) {
                displayItems.push(DisplayOptions.Legend)
            }
            return displayItems
        }

        if (isMetric) {
            displayItems.push(DisplayOptions.MetricSummary, DisplayOptions.MetricShowChange, DisplayOptions.MetricColor)
        }
        if (isLifecycle) {
            displayItems.push(DisplayOptions.LifecycleStacking)
        }
        if (supportsValueOnSeries) {
            displayItems.push(DisplayOptions.ValueLabels)
        }
        if (isLifecycle) {
            displayItems.push(DisplayOptions.LifecyclePercentages)
        }
        if (supportsPercentStackView) {
            displayItems.push(DisplayOptions.PercentStack)
        }
        if (supportsBarValueStacking) {
            displayItems.push(DisplayOptions.StackBreakdown)
        }
        if ((hasLegend || showFunnelLegendConfig) && !useQuillLegendOptions) {
            displayItems.push(DisplayOptions.Legend)
        }
        if (isPie) {
            displayItems.push(DisplayOptions.SliceNames, DisplayOptions.PieTotal)
        }
        if (isTrendsFunnel && !hideContinuousChartOptions) {
            displayItems.push(DisplayOptions.HideIncompleteFunnelPeriods)
        }
        if (showAnnotationsConfig) {
            displayItems.push(DisplayOptions.Annotations)
        }
        if (showAlertThresholdLinesConfig) {
            displayItems.push(DisplayOptions.AlertAnomalyPoints)
        }
        if (useQuillLegendOptions) {
            displayItems.push(DisplayOptions.LegendOptions)
        }
        return displayItems
    }

    const displaySections: DisplayOptionSection[] = []
    const displayItems = getDisplayItems()
    if (showDisplaySection && displayItems.length > 0) {
        displaySections.push({ key: 'display', dataAttr: 'options-display-section', items: displayItems })
    }
    if (showUnit) {
        displaySections.push({ key: 'unit', title: 'Unit', items: [DisplayOptions.Unit] })
    }
    if (supportsResultCustomizationBy) {
        displaySections.push({
            key: 'color-customization',
            title: 'Color customization by',
            tooltip:
                "You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).",
            items: [DisplayOptions.ResultCustomizationBy],
        })
    }
    if (showDecimalPlaces) {
        displaySections.push({
            key: 'decimal-places',
            title: 'Decimal places',
            items: [DisplayOptions.DecimalPrecision],
        })
    }
    if (isRetention) {
        displaySections.push({
            key: 'retention-dashboards',
            title: 'On dashboards',
            items: [DisplayOptions.RetentionDashboardDisplay],
        })
        displaySections.push({
            key: 'retention-cohort-labels',
            title: 'Cohort labels start at',
            tooltip:
                'Controls the starting index used to label cohort columns. Display only, does not affect the calculations.',
            items: [DisplayOptions.RetentionCohortLabelStart],
        })
    }

    // Scale sits directly above the range, so the log scale that disables the range is in view.
    const axesSections: DisplayOptionSection[] = []
    if (showAxisLabelsConfig) {
        axesSections.push({ key: 'x-axis', title: 'X-axis', items: [DisplayOptions.XAxisLabel] })
    }
    const yAxisItems: DisplayOption[] = []
    if (showAxisLabelsConfig) {
        yAxisItems.push(DisplayOptions.YAxisLabel)
    }
    if (showMultipleYAxesConfig) {
        yAxisItems.push(DisplayOptions.MultipleYAxes)
    }
    if (showYAxisScale) {
        yAxisItems.push(DisplayOptions.Scale)
    }
    if (showYAxisRangeConfig) {
        yAxisItems.push(DisplayOptions.YAxisRange)
    }
    if (yAxisItems.length > 0) {
        axesSections.push({ key: 'y-axis', title: 'Y-axis', items: yAxisItems })
    }

    const styleItems: DisplayOption[] = []
    if (showLineStyleConfig) {
        styleItems.push(DisplayOptions.LineStyle)
    }
    if (showSmoothing) {
        styleItems.push(DisplayOptions.Smoothing)
    }
    const overlayItems: DisplayOption[] = []
    if (showTrendLinesConfig && !isBoxPlot) {
        overlayItems.push(DisplayOptions.TrendLines)
    }
    if (showStatisticalOverlays) {
        overlayItems.push(DisplayOptions.MovingAverage)
        if (showMovingAverage) {
            overlayItems.push(DisplayOptions.MovingAverageIntervals)
        }
        overlayItems.push(DisplayOptions.ConfidenceInterval)
        if (showConfidenceIntervals) {
            overlayItems.push(DisplayOptions.ConfidenceLevel)
        }
    }
    if (showAlertThresholdLinesConfig && !isBoxPlot) {
        overlayItems.push(DisplayOptions.AlertThresholdLines)
    }
    const linesSections: DisplayOptionSection[] = []
    if (styleItems.length > 0) {
        linesSections.push({ key: 'style', title: 'Style', items: styleItems })
    }
    if (overlayItems.length > 0) {
        linesSections.push({
            key: 'overlays',
            title: 'Overlays',
            dataAttr: 'options-overlays-section',
            items: overlayItems,
        })
    }

    const unitIsSet =
        showUnit && !!trendsFilter?.aggregationAxisFormat && trendsFilter.aggregationAxisFormat !== 'numeric'
    const displayCount = countTruthy(
        supportsValueOnSeries && showValuesOnSeries,
        isLifecycle && showPercentagesOnSeries,
        showPercentStackView,
        isPie && trendsFilter?.showLabelsOnSeries,
        unitIsSet,
        (hasLegend || showFunnelLegendConfig) && showLegend,
        showAnnotationsConfig && showAnnotations === false,
        isMetric && trendsFilter?.metricShowChange === false,
        isMetric && trendsFilter?.metricColorByDirection,
        isMetric && !!trendsFilter?.metricSummary && trendsFilter.metricSummary !== 'total'
    )
    const axesCount = countTruthy(
        showMultipleYAxesConfig && showMultipleYAxes,
        showYAxisScale && !!yAxisScaleType && yAxisScaleType !== 'linear',
        showYAxisRangeConfig && trendsFilter?.yAxisStartAtZero === false,
        showYAxisRangeConfig && trendsFilter?.yAxisStartAtZero === false && typeof trendsFilter?.yAxisMin === 'number',
        showYAxisRangeConfig && typeof trendsFilter?.yAxisMax === 'number',
        showAxisLabelsConfig && !!normalizeAxisLabel(trendsFilter?.xAxisLabel),
        showAxisLabelsConfig && !!normalizeAxisLabel(trendsFilter?.yAxisLabel)
    )
    const linesCount = countTruthy(
        showSmoothing && (trendsFilter?.smoothingIntervals ?? 1) !== 1,
        showLineStyleConfig && (insightFilter as TrendsFilter | undefined)?.chartStyle?.curve === 'linear',
        showTrendLinesConfig && !isBoxPlot && (insightFilter as TrendsFilter | undefined)?.showTrendLines,
        showStatisticalOverlays && showMovingAverage,
        showStatisticalOverlays && showConfidenceIntervals,
        showAlertThresholdLinesConfig && !isBoxPlot && showAlertThresholdLines
    )

    const allTabs: DisplayOptionTab[] = [
        { key: 'general', label: 'General', sections: displaySections, count: displayCount },
        { key: 'axes', label: 'Axes', sections: axesSections, count: axesCount },
        { key: 'lines', label: 'Lines', sections: linesSections, count: linesCount },
    ]
    // Only trends has enough options to need tabs; the other insight types keep one flat list.
    const tabs = (
        isTrends
            ? allTabs
            : [
                  {
                      key: 'general' as const,
                      label: 'General',
                      sections: allTabs.flatMap((tab) => tab.sections),
                      count: allTabs.reduce((sum, tab) => sum + tab.count, 0),
                  },
              ]
    ).filter((tab) => tab.sections.length > 0)

    return { tabs, count: tabs.reduce((sum, tab) => sum + tab.count, 0) }
}
