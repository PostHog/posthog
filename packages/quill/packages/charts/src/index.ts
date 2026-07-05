// Components
export { BarChart } from './charts/BarChart/BarChart'
export type { BarChartProps } from './charts/BarChart/BarChart'
export { LineChart } from './charts/LineChart/LineChart'
export type { LineChartProps } from './charts/LineChart/LineChart'
export { ComboChart } from './charts/ComboChart/ComboChart'
export type { ComboChartProps } from './charts/ComboChart/ComboChart'
export { TimeSeriesLineChart } from './charts/TimeSeriesLineChart/TimeSeriesLineChart'
export type {
    ChartLoadingProps,
    ConfidenceIntervalConfig,
    MovingAverageConfig,
    TimeSeriesLineChartConfig,
    TimeSeriesLineChartProps,
    TrendLineConfig,
} from './charts/TimeSeriesLineChart/TimeSeriesLineChart'
export type { ValueLabelsConfig } from './charts/utils/use-value-labels'
export { TimeSeriesBarChart } from './charts/TimeSeriesBarChart/TimeSeriesBarChart'
export type { TimeSeriesBarChartConfig, TimeSeriesBarChartProps } from './charts/TimeSeriesBarChart/TimeSeriesBarChart'
export { TimeSeriesComboChart } from './charts/TimeSeriesComboChart/TimeSeriesComboChart'
export type {
    TimeSeriesComboChartConfig,
    TimeSeriesComboChartProps,
} from './charts/TimeSeriesComboChart/TimeSeriesComboChart'
export { Sparkline } from './charts/Sparkline/Sparkline'
export type { SparklineProps } from './charts/Sparkline/Sparkline'
export { MetricCard } from './components/MetricCard/MetricCard'
export type { MetricCardProps, ChangeColor, MetricChange } from './components/MetricCard/MetricCard'
// Headless metric helpers — the "metric engine" shared by `MetricCard` and reused by higher layers
// (quill-components' composable `Metric`) to build metric tiles on top of `Sparkline`.
export { resolveDelta } from './components/MetricCard/resolveDelta'
export type { ResolvedDelta } from './components/MetricCard/resolveDelta'
export { computeFallbackChangePercent } from './components/MetricCard/internals'
export { useAnimatedNumber } from './components/MetricCard/useAnimatedNumber'
export { useHoverIntent } from './components/MetricCard/useHoverIntent'

// Base chart (for building new chart types)
export { Chart } from './core/Chart'
export type { ChartProps } from './core/Chart'
export { ChartErrorBoundary } from './core/ChartErrorBoundary'
export { RadialChart } from './core/RadialChart'
export type { RadialChartProps, RadialLayoutBuilder } from './core/RadialChart'
export { DEFAULT_MARGINS } from './core/hooks/useChartMargins'

// Box plot
export { BoxPlot } from './charts/BoxPlot/BoxPlot'
export type {
    BoxPlotAdaptedMeta,
    BoxPlotClickData,
    BoxPlotConfig,
    BoxPlotProps,
    BoxPlotTooltipContext,
} from './charts/BoxPlot/BoxPlot'
export type { BoxPlotDatum, BoxPlotSeries } from './charts/BoxPlot/types'
export type { BoxRect } from './core/types'
export { BoxPlotTooltip } from './charts/BoxPlot/BoxPlotTooltip'
export type { BoxPlotTooltipProps } from './charts/BoxPlot/BoxPlotTooltip'

// Slope chart
export { SlopeChart } from './charts/SlopeChart/SlopeChart'
export type {
    SlopeChartConfig,
    SlopeChartLegendConfig,
    SlopeChartProps,
    SlopeSeriesMeta,
} from './charts/SlopeChart/SlopeChart'
export { SlopeValueLabels } from './charts/SlopeChart/SlopeValueLabels'
export type { SlopeValueLabelsProps } from './charts/SlopeChart/SlopeValueLabels'
export { SlopeSeriesLabels } from './charts/SlopeChart/SlopeSeriesLabels'
export type { SlopeSeriesLabelsProps } from './charts/SlopeChart/SlopeSeriesLabels'
export { slopeLegendItems } from './charts/SlopeChart/slope-legend'

// Pie / donut
export { PieChart } from './charts/PieChart/PieChart'
export type { PieChartConfig, PieChartProps } from './charts/PieChart/PieChart'
export { computePieLayout, cursorOffsetToAngle, sliceAt, defaultSliceValue } from './charts/PieChart/computePieLayout'
export type { PieLayout, PieSlice } from './charts/PieChart/computePieLayout'
export { SliceLabels } from './charts/PieChart/SliceLabels'
export type { SliceLabelsProps } from './charts/PieChart/SliceLabels'
export { PieTooltip } from './charts/PieChart/PieTooltip'
export type { PieTooltipProps } from './charts/PieChart/PieTooltip'
export { useRadialLayout } from './core/radial-context'
export type { RadialLayoutContextValue } from './core/radial-context'
export type { RadialSlicePayload } from './core/hooks/useRadialInteraction'

// Chart context (for custom overlay children)
export { useChart, useChartHover, useChartLayout } from './core/chart-context'
export type { BaseChartContext, ChartHoverContextValue, ChartLayoutContextValue } from './core/chart-context'
export type { Gutter } from './core/y-axis-gutters'

// Core types
export type {
    BarChartConfig,
    BarsConfig,
    ChartConfig,
    ChartLegendConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    ComboChartConfig,
    CreateScalesFn,
    DateRangeZoomData,
    DragRect,
    LineChartConfig,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    Series,
    SeriesType,
    TooltipConfig,
    TooltipContext,
    ValueDomain,
    YAxis,
    YAxisScale,
} from './core/types'
export { DEFAULT_Y_AXIS_ID } from './core/types'

// Theme: read a ChartTheme from quill data-viz CSS vars (with a built-in fallback palette)
export { themeFromCssVars, useChartTheme, DEFAULT_CHART_COLORS } from './core/theme'
export type { ThemeFromCssOptions } from './core/theme'

// Built-in tooltip (for reference or extension)
export { DefaultTooltip, type DefaultTooltipProps } from './overlays/DefaultTooltip'
// Shared tooltip surface — reuse to build custom tooltips with the quill look
export { TooltipSurface, TooltipSwatch } from './overlays/TooltipSurface'

// Optional overlays
export { ReferenceLine, ReferenceLines } from './overlays/ReferenceLine'
export type {
    ReferenceLineFillSide,
    ReferenceLineLabelPosition,
    ReferenceLineOrientation,
    ReferenceLineProps,
    ReferenceLineStroke,
    ReferenceLineStyle,
    ReferenceLineVariant,
} from './overlays/ReferenceLine'
export { ChartLoadingOverlay } from './overlays/ChartLoadingOverlay'
export type { ChartLoadingOverlayProps } from './overlays/ChartLoadingOverlay'
export { ValueLabels } from './overlays/ValueLabels'
export type { ValueLabelContext, ValueLabelFormatter, ValueLabelsProps } from './overlays/ValueLabels'
export { AxisTitles } from './overlays/AxisTitles'
export type { AxisTitlesProps } from './overlays/AxisTitles'

// Helper for adapters that need to align with the same x-axis tick selection the chart draws.
export { computeVisibleXLabels } from './overlays/AxisLabels'

export { AnomalyPointsLayer } from './overlays/AnomalyPointsLayer'
export type { AnomalyMarker } from './overlays/AnomalyPointsLayer'
export { movingAverageKey } from './charts/utils/derived-series'

// Timeseries utils
export { createXAxisTickCallback } from './utils/dates'
export type { TimeInterval } from './utils/dates'
export { buildYTickFormatter } from './utils/y-formatters'
export type { YAxisFormat, YFormatterConfig } from './utils/y-formatters'
export { percentage } from './utils/format'
export type { XAxisConfig, YAxisConfig } from './utils/use-axis-formatters'
export { buildGoalLineReferenceLines, computeSeriesNonZeroMax } from './utils/goal-lines'
export type { GoalLineConfig } from './utils/goal-lines'
export { normalizeAxisLabel } from './utils/axis-labels'
export { MAX_CATEGORY_LABEL_WIDTH } from './utils/text-measure'

// Statistics helpers (used by trend-line / moving-average / confidence-interval features)
export { ciRanges, linearRegression, movingAverage, trendLine } from './utils/statistics'

// Generic UI primitives (no canvas) — composed alongside charts by adapters
export { Legend } from './components/Legend/Legend'
export type { LegendItem, LegendProps } from './components/Legend/Legend'
export { ChartLegend } from './components/Legend/ChartLegend'
export type { ChartLegendProps } from './components/Legend/ChartLegend'
export { legendItemsFromSeries } from './components/Legend/legendItemsFromSeries'
export { useChartLegend, applyHiddenSeries } from './components/Legend/useChartLegend'
export type { ChartLegendRenderProps, ChartLegendState } from './components/Legend/useChartLegend'
