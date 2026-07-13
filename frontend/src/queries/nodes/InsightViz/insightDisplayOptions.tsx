import { useValues } from 'kea'

import { normalizeAxisLabel } from '@posthog/quill-charts'

import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { hasBreakdownFilter } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import {
    BAR_DISPLAYS,
    displayMatches,
    DisplayOptions,
    isDefaultTrendsLineDisplay,
    LINE_DISPLAYS,
    SectionHeader,
} from './DisplayOptions'

// The "Options" menu in the insight editor's display config bar. `count` is the number of non-default
// active options, badged on the Options button.
export function useInsightDisplayOptions(): { items: LemonMenuItems; count: number } {
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
        showAnnotations,
        isNonTimeSeriesDisplay,
        interval,
        usesInChartLegend,
    } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const {
        showValuesOnSeries,
        showPercentagesOnSeries,
        mightContainFractionalNumbers,
        showConfidenceIntervals,
        showMovingAverage,
    } = useValues(trendsDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const hideWeekendsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS]
    const quillLegendEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]

    // The slope graph shows the first vs last interval, so it drops the options that need the points
    // between them (smoothing, multiple axes, alert/annotation overlays, statistical analysis).
    const isSlopeGraph = display === ChartDisplayType.SlopeGraph
    const isMetric = display === ChartDisplayType.Metric
    const hideContinuousChartOptions = isNonTimeSeriesDisplay || isMetric || isSlopeGraph
    const showSmoothing =
        isTrends &&
        !hasBreakdownFilter(breakdownFilter) &&
        (!display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph) &&
        !!interval &&
        (smoothingOptions[interval]?.length ?? 0) > 0
    const showMultipleYAxesConfig = (isTrends || isStickiness) && !hideContinuousChartOptions
    const showAlertThresholdLinesConfig = isTrends && !hideContinuousChartOptions
    const showAnnotationsConfig = (isTrends && !hideContinuousChartOptions) || isTrendsFunnel
    // Stickiness defaults to its line chart when display is unset, same as trends does — but
    // isDefaultTrendsLineDisplay only matches TrendsQuery, so we handle the stickiness case here.
    const isLineDisplay =
        isDefaultTrendsLineDisplay(display, querySource) ||
        displayMatches(display, LINE_DISPLAYS) ||
        (!display && isStickiness)
    const isBarDisplay = displayMatches(display, BAR_DISPLAYS)
    const showAxisLabelsConfig = isTrends && (isLineDisplay || isBarDisplay)
    const showFunnelLegendConfig = isTrendsFunnel && hasBreakdownFilter(breakdownFilter)
    const isBoxPlot = display === ChartDisplayType.BoxPlot
    const isCalendarHeatmap = display === ChartDisplayType.CalendarHeatmap
    // When the chart draws its own positioned in-chart legend, show the position selector instead
    // of the legacy show/hide checkbox. usesInChartLegend is the single source of truth (same
    // selector used by InsightVizDisplay to suppress the side legend). Funnel trends with breakdown
    // also get the position selector since they render the quill legend via config.legend.
    const useQuillLegendOptions = usesInChartLegend || (quillLegendEnabled && showFunnelLegendConfig)

    const showDisplaySection =
        (isTrends && !isCalendarHeatmap) || isRetention || isTrendsFunnel || isStickiness || isLifecycle
    const showYAxisScale = !hideContinuousChartOptions && isTrends && !isCalendarHeatmap

    // The box plot and slope graph only show a couple of options each; everything else falls
    // through to the full shared list.
    const getDisplayItems = (): LemonMenuItem[] => {
        const displayItems: LemonMenuItem[] = []

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
        if (display === ChartDisplayType.ActionsPie) {
            displayItems.push(DisplayOptions.PieTotal)
        }
        if (showAlertThresholdLinesConfig) {
            displayItems.push(DisplayOptions.AlertThresholdLines, DisplayOptions.AlertAnomalyPoints)
        }
        if (showMultipleYAxesConfig) {
            displayItems.push(DisplayOptions.MultipleYAxes)
        }
        if ((isTrends || isRetention || isTrendsFunnel) && !hideContinuousChartOptions) {
            displayItems.push(DisplayOptions.TrendLines)
        }
        if (isTrendsFunnel && !hideContinuousChartOptions) {
            displayItems.push(DisplayOptions.HideIncompleteFunnelPeriods)
        }
        if (isTrends && !hideContinuousChartOptions && hideWeekendsEnabled) {
            displayItems.push(DisplayOptions.HideWeekends)
        }
        if (showAnnotationsConfig) {
            displayItems.push(DisplayOptions.Annotations)
        }
        if (useQuillLegendOptions) {
            displayItems.push(DisplayOptions.LegendOptions)
        }
        return displayItems
    }

    const items: LemonMenuItems = []

    if (showSmoothing) {
        items.push({ title: 'Smoothing', items: [DisplayOptions.Smoothing] })
    }

    if (showDisplaySection) {
        items.push({
            title: <SectionHeader dataAttr="options-display-section">Display</SectionHeader>,
            items: getDisplayItems(),
        })
    }

    if (supportsResultCustomizationBy) {
        items.push({
            title: (
                <SectionHeader tooltip="You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).">
                    Color customization by
                </SectionHeader>
            ),
            items: [DisplayOptions.ResultCustomizationBy],
        })
    }

    if (!showPercentStackView && isTrends && !isCalendarHeatmap) {
        items.push({
            title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
            items: [DisplayOptions.Unit],
        })
    }

    if (showYAxisScale) {
        items.push({ title: 'Y-axis scale', items: [DisplayOptions.Scale] })
    }

    if (showYAxisScale && !isBoxPlot) {
        const statisticalItems: LemonMenuItem[] = [DisplayOptions.ConfidenceInterval]
        if (showConfidenceIntervals) {
            statisticalItems.push(DisplayOptions.ConfidenceLevel)
        }
        statisticalItems.push(DisplayOptions.MovingAverage)
        if (showMovingAverage) {
            statisticalItems.push(DisplayOptions.MovingAverageIntervals)
        }
        items.push({ title: 'Statistical analysis', items: statisticalItems })
    }

    if (showAxisLabelsConfig) {
        items.push({ title: 'Axis labels', items: [DisplayOptions.AxisLabels] })
    }

    if (mightContainFractionalNumbers && isTrends && !isCalendarHeatmap) {
        items.push({ title: 'Decimal places', items: [DisplayOptions.DecimalPrecision] })
    }

    if (isRetention) {
        items.push({ title: 'On dashboards', items: [DisplayOptions.RetentionDashboardDisplay] })
        items.push({
            title: (
                <SectionHeader tooltip="Controls the starting index used to label cohort columns. Display only, does not affect the calculations.">
                    Cohort labels start at
                </SectionHeader>
            ),
            items: [DisplayOptions.RetentionCohortLabelStart],
        })
    }

    const count: number =
        (showSmoothing && (trendsFilter?.smoothingIntervals ?? 1) !== 1 ? 1 : 0) +
        (supportsValueOnSeries && showValuesOnSeries ? 1 : 0) +
        (isLifecycle && showPercentagesOnSeries ? 1 : 0) +
        (showPercentStackView ? 1 : 0) +
        (!showPercentStackView &&
        isTrends &&
        trendsFilter?.aggregationAxisFormat &&
        trendsFilter.aggregationAxisFormat !== 'numeric'
            ? 1
            : 0) +
        ((hasLegend || showFunnelLegendConfig) && showLegend ? 1 : 0) +
        (!!yAxisScaleType && yAxisScaleType !== 'linear' ? 1 : 0) +
        (showAxisLabelsConfig && normalizeAxisLabel(trendsFilter?.xAxisLabel) ? 1 : 0) +
        (showAxisLabelsConfig && normalizeAxisLabel(trendsFilter?.yAxisLabel) ? 1 : 0) +
        (showMultipleYAxes ? 1 : 0) +
        (trendsFilter?.hideWeekends && hideWeekendsEnabled ? 1 : 0) +
        (showAnnotationsConfig && showAnnotations === false ? 1 : 0) +
        (isMetric && trendsFilter?.metricShowChange === false ? 1 : 0) +
        (isMetric && trendsFilter?.metricColorByDirection ? 1 : 0) +
        (isMetric && !!trendsFilter?.metricSummary && trendsFilter.metricSummary !== 'total' ? 1 : 0)

    return { items, count }
}
