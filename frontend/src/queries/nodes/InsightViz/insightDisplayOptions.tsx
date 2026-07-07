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

// The "Options" (and flag-gated "Style") menus in the insight editor's display config bar. `count`
// and `styleCount` are the number of non-default active options, badged on the respective buttons.
export function useInsightDisplayOptions(): {
    items: LemonMenuItems
    count: number
    styleItems: LemonMenuItems
    styleCount: number
} {
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
    // With the Overlays editor panel section enabled, the overlay toggles (trend lines, alert
    // overlays, annotations, statistical analysis) move there and leave this menu.
    const overlaysSectionEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHT_OVERLAYS_SECTION]
    // With the Style menu enabled, the presentation options (value labels, legend, number format,
    // axis labels, pie/metric presentation, color assignment) move to their own toolbar menu.
    const styleMenuEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHT_STYLE_MENU]

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
    // The chart style options are only wired into the quill trends line/area charts for now
    const showLineStyleConfig = isTrends && isLineDisplay
    const chartStyle = trendsFilter?.chartStyle
    const defaultCurve = featureFlags[FEATURE_FLAGS.QUILL_CHART_STYLE_REFRESH] ? 'smooth' : 'linear'
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
            if (hasLegend && !styleMenuEnabled) {
                displayItems.push(DisplayOptions.Legend)
            }
            displayItems.push(DisplayOptions.ExcludeOutliers)
            return displayItems
        }

        if (isSlopeGraph) {
            // A slope only shows the first vs last interval of each series — the legend (when there
            // are multiple series) is the only display option that applies.
            if (hasLegend && !styleMenuEnabled) {
                displayItems.push(DisplayOptions.Legend)
            }
            return displayItems
        }

        if (isMetric) {
            displayItems.push(DisplayOptions.MetricSummary)
            if (!styleMenuEnabled) {
                displayItems.push(DisplayOptions.MetricShowChange, DisplayOptions.MetricColor)
            }
        }
        if (isLifecycle) {
            displayItems.push(DisplayOptions.LifecycleStacking)
        }
        if (supportsValueOnSeries && !styleMenuEnabled) {
            displayItems.push(DisplayOptions.ValueLabels)
        }
        if (isLifecycle && !styleMenuEnabled) {
            displayItems.push(DisplayOptions.LifecyclePercentages)
        }
        if (supportsPercentStackView) {
            displayItems.push(DisplayOptions.PercentStack)
        }
        if (supportsBarValueStacking) {
            displayItems.push(DisplayOptions.StackBreakdown)
        }
        if ((hasLegend || showFunnelLegendConfig) && !useQuillLegendOptions && !styleMenuEnabled) {
            displayItems.push(DisplayOptions.Legend)
        }
        if (display === ChartDisplayType.ActionsPie && !styleMenuEnabled) {
            displayItems.push(DisplayOptions.PieTotal)
        }
        if (showAlertThresholdLinesConfig && !overlaysSectionEnabled) {
            displayItems.push(DisplayOptions.AlertThresholdLines, DisplayOptions.AlertAnomalyPoints)
        }
        if (showMultipleYAxesConfig) {
            displayItems.push(DisplayOptions.MultipleYAxes)
        }
        if ((isTrends || isRetention || isTrendsFunnel) && !hideContinuousChartOptions && !overlaysSectionEnabled) {
            displayItems.push(DisplayOptions.TrendLines)
        }
        if (isTrendsFunnel && !hideContinuousChartOptions) {
            displayItems.push(DisplayOptions.HideIncompleteFunnelPeriods)
        }
        if (isTrends && !hideContinuousChartOptions && hideWeekendsEnabled) {
            displayItems.push(DisplayOptions.HideWeekends)
        }
        if (showAnnotationsConfig && !overlaysSectionEnabled) {
            displayItems.push(DisplayOptions.Annotations)
        }
        if (useQuillLegendOptions && !styleMenuEnabled) {
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

    if (supportsResultCustomizationBy && !styleMenuEnabled) {
        items.push({
            title: (
                <SectionHeader tooltip="You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).">
                    Color customization by
                </SectionHeader>
            ),
            items: [DisplayOptions.ResultCustomizationBy],
        })
    }

    if (!showPercentStackView && isTrends && !isCalendarHeatmap && !styleMenuEnabled) {
        items.push({
            title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
            items: [DisplayOptions.Unit],
        })
    }

    if (showYAxisScale) {
        items.push({ title: 'Y-axis scale', items: [DisplayOptions.Scale] })
    }

    if (showYAxisScale && !isBoxPlot && !overlaysSectionEnabled) {
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

    if (showAxisLabelsConfig && !styleMenuEnabled) {
        items.push({ title: 'Axis labels', items: [DisplayOptions.AxisLabels] })
    }

    if (mightContainFractionalNumbers && isTrends && !isCalendarHeatmap && !styleMenuEnabled) {
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

    // The Style menu: pure presentation options — none of them change the computed numbers or add
    // data to the chart. Conditions mirror the ones getDisplayItems/the sections above use, so each
    // option keeps appearing for exactly the same insights, just in the other menu.
    const styleItems: LemonMenuItems = []
    if (styleMenuEnabled) {
        const labelsAndLegendItems: LemonMenuItem[] = []
        if (isMetric) {
            labelsAndLegendItems.push(DisplayOptions.MetricShowChange, DisplayOptions.MetricColor)
        }
        if (supportsValueOnSeries && !isBoxPlot && !isSlopeGraph) {
            labelsAndLegendItems.push(DisplayOptions.ValueLabels)
        }
        if (isLifecycle) {
            labelsAndLegendItems.push(DisplayOptions.LifecyclePercentages)
        }
        if (isBoxPlot || isSlopeGraph) {
            if (hasLegend) {
                labelsAndLegendItems.push(DisplayOptions.Legend)
            }
        } else if (useQuillLegendOptions) {
            labelsAndLegendItems.push(DisplayOptions.LegendOptions)
        } else if (hasLegend || showFunnelLegendConfig) {
            labelsAndLegendItems.push(DisplayOptions.Legend)
        }
        if (display === ChartDisplayType.ActionsPie) {
            labelsAndLegendItems.push(DisplayOptions.PieTotal)
        }
        if (labelsAndLegendItems.length > 0) {
            styleItems.push({
                title: <SectionHeader dataAttr="style-labels-section">Labels & legend</SectionHeader>,
                items: labelsAndLegendItems,
            })
        }
        if (showLineStyleConfig) {
            styleItems.push({
                title: <SectionHeader dataAttr="style-line-section">Line style</SectionHeader>,
                items: [
                    DisplayOptions.LineShape,
                    DisplayOptions.LineStyle,
                    DisplayOptions.ShowPoints,
                    DisplayOptions.GridLines,
                ],
            })
        }
        if (supportsResultCustomizationBy) {
            styleItems.push({
                title: (
                    <SectionHeader tooltip="You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).">
                        Color customization by
                    </SectionHeader>
                ),
                items: [DisplayOptions.ResultCustomizationBy],
            })
        }
        if (!showPercentStackView && isTrends && !isCalendarHeatmap) {
            styleItems.push({
                title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
                items: [DisplayOptions.Unit],
            })
        }
        if (mightContainFractionalNumbers && isTrends && !isCalendarHeatmap) {
            styleItems.push({ title: 'Decimal places', items: [DisplayOptions.DecimalPrecision] })
        }
        if (showAxisLabelsConfig) {
            styleItems.push({ title: 'Axis labels', items: [DisplayOptions.AxisLabels] })
        }
    }

    // Non-default presentation options — badged on the Style button when it's enabled, otherwise
    // on the Options button along with everything else.
    const styleCount: number =
        (supportsValueOnSeries && showValuesOnSeries ? 1 : 0) +
        (isLifecycle && showPercentagesOnSeries ? 1 : 0) +
        (!showPercentStackView &&
        isTrends &&
        trendsFilter?.aggregationAxisFormat &&
        trendsFilter.aggregationAxisFormat !== 'numeric'
            ? 1
            : 0) +
        ((hasLegend || showFunnelLegendConfig) && showLegend ? 1 : 0) +
        (showAxisLabelsConfig && normalizeAxisLabel(trendsFilter?.xAxisLabel) ? 1 : 0) +
        (showAxisLabelsConfig && normalizeAxisLabel(trendsFilter?.yAxisLabel) ? 1 : 0) +
        (isMetric && trendsFilter?.metricShowChange === false ? 1 : 0) +
        (isMetric && trendsFilter?.metricColorByDirection ? 1 : 0) +
        (showLineStyleConfig && chartStyle?.curve && chartStyle.curve !== defaultCurve ? 1 : 0) +
        (showLineStyleConfig && chartStyle?.lineStyle && chartStyle.lineStyle !== 'solid' ? 1 : 0) +
        (showLineStyleConfig && chartStyle?.showPoints ? 1 : 0) +
        (showLineStyleConfig && chartStyle?.showGrid === false ? 1 : 0)

    const optionsCount: number =
        (showSmoothing && (trendsFilter?.smoothingIntervals ?? 1) !== 1 ? 1 : 0) +
        (showPercentStackView ? 1 : 0) +
        (!!yAxisScaleType && yAxisScaleType !== 'linear' ? 1 : 0) +
        (showMultipleYAxes ? 1 : 0) +
        (trendsFilter?.hideWeekends && hideWeekendsEnabled ? 1 : 0) +
        (showAnnotationsConfig && !overlaysSectionEnabled && showAnnotations === false ? 1 : 0) +
        (isMetric && !!trendsFilter?.metricSummary && trendsFilter.metricSummary !== 'total' ? 1 : 0)

    return {
        items,
        count: optionsCount + (styleMenuEnabled ? 0 : styleCount),
        styleItems,
        styleCount: styleMenuEnabled ? styleCount : 0,
    }
}
