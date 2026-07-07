import { useValues } from 'kea'

import { normalizeAxisLabel } from '@posthog/quill-charts'

import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { AxisLabelsFilter } from 'scenes/insights/EditorFilters/AxisLabelsFilter'
import {
    GradientFillFilter,
    LineShapePicker,
    LineStylePicker,
    ShowGridLinesFilter,
    ShowPointsFilter,
} from 'scenes/insights/EditorFilters/ChartStyleFilters'
import { ScalePicker } from 'scenes/insights/EditorFilters/ScalePicker'
import { ShowMultipleYAxesFilter } from 'scenes/insights/EditorFilters/ShowMultipleYAxesFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { hasBreakdownFilter } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import {
    BAR_DISPLAYS,
    CollapsibleOptionsSection,
    DecimalPrecision,
    displayMatches,
    DisplayOptions,
    isDefaultTrendsLineDisplay,
    LINE_DISPLAYS,
    SectionHeader,
} from './DisplayOptions'

/** Everything the Options menu and its accordion sections need to decide what to show. Shared
 * between useInsightDisplayOptions and the module-level accordion components below, so those
 * components keep a stable identity — an inline component recreated per render would remount
 * (and reset its expansion state) every time the menu re-renders. */
function useDisplayOptionsState() {
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
    // With the style menu flag enabled, the menu is reorganized into accordions: Display (auto-open),
    // Line style (chart style controls), and Axes (unit, scale, labels, decimal places).
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
    const showUnitPicker = !showPercentStackView && isTrends && !isCalendarHeatmap
    const showDecimalPlaces = mightContainFractionalNumbers && isTrends && !isCalendarHeatmap

    return {
        display,
        isTrends,
        isRetention,
        isLifecycle,
        isMetric,
        isBoxPlot,
        isSlopeGraph,
        isCalendarHeatmap,
        isTrendsFunnel,
        hideContinuousChartOptions,
        trendsFilter,
        chartStyle,
        defaultCurve,
        yAxisScaleType,
        hasLegend,
        showLegend,
        supportsValueOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        supportsBarValueStacking,
        supportsResultCustomizationBy,
        showMultipleYAxes,
        showAnnotations,
        showValuesOnSeries,
        showPercentagesOnSeries,
        showConfidenceIntervals,
        showMovingAverage,
        hideWeekendsEnabled,
        overlaysSectionEnabled,
        styleMenuEnabled,
        showSmoothing,
        showMultipleYAxesConfig,
        showAlertThresholdLinesConfig,
        showAnnotationsConfig,
        showAxisLabelsConfig,
        showLineStyleConfig,
        showFunnelLegendConfig,
        useQuillLegendOptions,
        showDisplaySection,
        showYAxisScale,
        showUnitPicker,
        showDecimalPlaces,
    }
}

type DisplayOptionsState = ReturnType<typeof useDisplayOptionsState>

// The box plot and slope graph only show a couple of options each; everything else falls
// through to the full shared list.
function getDisplayItems(s: DisplayOptionsState): LemonMenuItem[] {
    const displayItems: LemonMenuItem[] = []

    if (s.isBoxPlot) {
        if (s.hasLegend) {
            displayItems.push(DisplayOptions.Legend)
        }
        displayItems.push(DisplayOptions.ExcludeOutliers)
        return displayItems
    }

    if (s.isSlopeGraph) {
        // A slope only shows the first vs last interval of each series — the legend (when there
        // are multiple series) is the only display option that applies.
        if (s.hasLegend) {
            displayItems.push(DisplayOptions.Legend)
        }
        return displayItems
    }

    if (s.isMetric) {
        displayItems.push(DisplayOptions.MetricSummary, DisplayOptions.MetricShowChange, DisplayOptions.MetricColor)
    }
    if (s.isLifecycle) {
        displayItems.push(DisplayOptions.LifecycleStacking)
    }
    if (s.supportsValueOnSeries) {
        displayItems.push(DisplayOptions.ValueLabels)
    }
    if (s.isLifecycle) {
        displayItems.push(DisplayOptions.LifecyclePercentages)
    }
    if (s.supportsPercentStackView) {
        displayItems.push(DisplayOptions.PercentStack)
    }
    if (s.supportsBarValueStacking) {
        displayItems.push(DisplayOptions.StackBreakdown)
    }
    if ((s.hasLegend || s.showFunnelLegendConfig) && !s.useQuillLegendOptions) {
        displayItems.push(DisplayOptions.Legend)
    }
    if (s.display === ChartDisplayType.ActionsPie) {
        displayItems.push(DisplayOptions.PieTotal)
    }
    if (s.showAlertThresholdLinesConfig && !s.overlaysSectionEnabled) {
        displayItems.push(DisplayOptions.AlertThresholdLines, DisplayOptions.AlertAnomalyPoints)
    }
    if (s.showMultipleYAxesConfig && !s.styleMenuEnabled) {
        displayItems.push(DisplayOptions.MultipleYAxes)
    }
    if (
        (s.isTrends || s.isRetention || s.isTrendsFunnel) &&
        !s.hideContinuousChartOptions &&
        !s.overlaysSectionEnabled
    ) {
        displayItems.push(DisplayOptions.TrendLines)
    }
    if (s.isTrendsFunnel && !s.hideContinuousChartOptions) {
        displayItems.push(DisplayOptions.HideIncompleteFunnelPeriods)
    }
    if (s.isTrends && !s.hideContinuousChartOptions && s.hideWeekendsEnabled) {
        displayItems.push(DisplayOptions.HideWeekends)
    }
    if (s.showAnnotationsConfig && !s.overlaysSectionEnabled) {
        displayItems.push(DisplayOptions.Annotations)
    }
    if (s.useQuillLegendOptions) {
        displayItems.push(DisplayOptions.LegendOptions)
    }
    return displayItems
}

// The accordion sections live at module level so their component identity is stable across
// renders. Defining them inline in the hook would remount them — and reset their expansion
// state and control internals — on every menu re-render.

function DisplayOptionsAccordion(): JSX.Element {
    const state = useDisplayOptionsState()

    return (
        <CollapsibleOptionsSection label="Display" dataAttr="options-display-section" defaultExpanded>
            {getDisplayItems(state).map((item, index) => {
                // Registry entries always use component labels
                const Label = item.label as () => JSX.Element
                return <Label key={index} />
            })}
        </CollapsibleOptionsSection>
    )
}

function LineStyleOptionsAccordion(): JSX.Element {
    return (
        <CollapsibleOptionsSection label="Line style" dataAttr="options-line-style-section">
            <LineShapePicker />
            <LineStylePicker />
            <ShowPointsFilter />
            <GradientFillFilter />
        </CollapsibleOptionsSection>
    )
}

function AxesOptionsAccordion(): JSX.Element {
    const {
        display,
        showUnitPicker,
        showYAxisScale,
        showMultipleYAxesConfig,
        showAxisLabelsConfig,
        showDecimalPlaces,
        showLineStyleConfig,
    } = useDisplayOptionsState()

    return (
        <CollapsibleOptionsSection label="Axes" dataAttr="options-axes-section">
            {showUnitPicker && (
                <>
                    <SectionHeader>{axisLabel(display || ChartDisplayType.ActionsLineGraph)}</SectionHeader>
                    <UnitPicker />
                </>
            )}
            {showYAxisScale && (
                <>
                    <SectionHeader>Y-axis scale</SectionHeader>
                    <ScalePicker />
                </>
            )}
            {showMultipleYAxesConfig && <ShowMultipleYAxesFilter />}
            {/* Gridlines are only wired into the quill line/area charts, same as the Line style controls */}
            {showLineStyleConfig && <ShowGridLinesFilter />}
            {showAxisLabelsConfig && (
                <>
                    <SectionHeader>Axis labels</SectionHeader>
                    <AxisLabelsFilter />
                </>
            )}
            {showDecimalPlaces && (
                <>
                    <SectionHeader>Decimal places</SectionHeader>
                    <DecimalPrecision />
                </>
            )}
        </CollapsibleOptionsSection>
    )
}

// The "Options" menu in the insight editor's display config bar. `count` is the number of non-default
// active options, badged on the Options button.
export function useInsightDisplayOptions(): { items: LemonMenuItems; count: number } {
    const state = useDisplayOptionsState()
    const {
        display,
        isTrends,
        isRetention,
        isLifecycle,
        isMetric,
        isBoxPlot,
        trendsFilter,
        chartStyle,
        defaultCurve,
        yAxisScaleType,
        hasLegend,
        showLegend,
        supportsValueOnSeries,
        showPercentStackView,
        supportsResultCustomizationBy,
        showMultipleYAxes,
        showAnnotations,
        showValuesOnSeries,
        showPercentagesOnSeries,
        showConfidenceIntervals,
        showMovingAverage,
        hideWeekendsEnabled,
        overlaysSectionEnabled,
        styleMenuEnabled,
        showSmoothing,
        showMultipleYAxesConfig,
        showAnnotationsConfig,
        showAxisLabelsConfig,
        showLineStyleConfig,
        showFunnelLegendConfig,
        showDisplaySection,
        showYAxisScale,
        showUnitPicker,
        showDecimalPlaces,
    } = state

    const items: LemonMenuItems = []

    const pushStatisticalSection = (): void => {
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
    }

    if (styleMenuEnabled) {
        // Reorganized menu: Display leads and auto-opens, the rarely used options collapse into the
        // Line style / Axes accordions, and the smoothing and color-assignment sections are dropped
        // entirely — usage data shows they barely register (smoothing is set on <1% of saved trends
        // insights).
        const accordionRows: LemonMenuItem[] = []
        if (showDisplaySection) {
            accordionRows.push({ label: DisplayOptionsAccordion })
        }
        if (showLineStyleConfig) {
            accordionRows.push({ label: LineStyleOptionsAccordion })
        }
        if (showUnitPicker || showYAxisScale || showMultipleYAxesConfig || showAxisLabelsConfig || showDecimalPlaces) {
            accordionRows.push({ label: AxesOptionsAccordion })
        }
        if (accordionRows.length > 0) {
            items.push({ items: accordionRows })
        }
        pushStatisticalSection()
    } else {
        if (showSmoothing) {
            items.push({ title: 'Smoothing', items: [DisplayOptions.Smoothing] })
        }
        if (showDisplaySection) {
            items.push({
                title: <SectionHeader dataAttr="options-display-section">Display</SectionHeader>,
                items: getDisplayItems(state),
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
        if (showUnitPicker) {
            items.push({
                title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
                items: [DisplayOptions.Unit],
            })
        }
        if (showYAxisScale) {
            items.push({ title: 'Y-axis scale', items: [DisplayOptions.Scale] })
        }
        pushStatisticalSection()
        if (showAxisLabelsConfig) {
            items.push({ title: 'Axis labels', items: [DisplayOptions.AxisLabels] })
        }
        if (showDecimalPlaces) {
            items.push({ title: 'Decimal places', items: [DisplayOptions.DecimalPrecision] })
        }
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
        (showLineStyleConfig && chartStyle?.gradientFill ? 1 : 0) +
        (showLineStyleConfig && chartStyle?.showGrid === false ? 1 : 0)

    const optionsCount: number =
        // The smoothing control is dropped from the reorganized menu, so don't badge for it there
        (showSmoothing && !styleMenuEnabled && (trendsFilter?.smoothingIntervals ?? 1) !== 1 ? 1 : 0) +
        (showPercentStackView ? 1 : 0) +
        (!!yAxisScaleType && yAxisScaleType !== 'linear' ? 1 : 0) +
        (showMultipleYAxes ? 1 : 0) +
        (trendsFilter?.hideWeekends && hideWeekendsEnabled ? 1 : 0) +
        (showAnnotationsConfig && !overlaysSectionEnabled && showAnnotations === false ? 1 : 0) +
        (isMetric && !!trendsFilter?.metricSummary && trendsFilter.metricSummary !== 'total' ? 1 : 0)

    return { items, count: optionsCount + styleCount }
}
