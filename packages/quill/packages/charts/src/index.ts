// Components
export { BarChart } from './charts/BarChart/BarChart'
export type { BarChartProps } from './charts/BarChart/BarChart'
export { LineChart } from './charts/LineChart/LineChart'
export type { LineChartProps } from './charts/LineChart/LineChart'
export { TimeSeriesLineChart } from './charts/TimeSeriesLineChart/TimeSeriesLineChart'
export type {
    ConfidenceIntervalConfig,
    MovingAverageConfig,
    TimeSeriesLineChartConfig,
    TimeSeriesLineChartProps,
    TrendLineConfig,
} from './charts/TimeSeriesLineChart/TimeSeriesLineChart'
export type { ValueLabelsConfig } from './charts/utils/use-value-labels'
export { TimeSeriesBarChart } from './charts/TimeSeriesBarChart/TimeSeriesBarChart'
export type { TimeSeriesBarChartConfig, TimeSeriesBarChartProps } from './charts/TimeSeriesBarChart/TimeSeriesBarChart'
export { Sparkline } from './charts/Sparkline/Sparkline'
export type { SparklineProps } from './charts/Sparkline/Sparkline'
export { Metric } from './blocks/Metric/Metric'
export type { ChangeColor, MetricChange, MetricProps } from './blocks/Metric/Metric'

// Base chart (for building new chart types)
export { Chart } from './core/Chart'
export type { ChartProps } from './core/Chart'
export { RadialChart, RADIAL_MARGINS } from './core/RadialChart'
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
export { computeBoxBand, computeBoxRect, computeSeriesBoxes } from './charts/BoxPlot/computeBoxLayout'
export type { BoxPlotDatum, BoxPlotSeries, BoxRect } from './charts/BoxPlot/computeBoxLayout'
export { BoxPlotTooltip } from './charts/BoxPlot/BoxPlotTooltip'
export type { BoxPlotTooltipProps } from './charts/BoxPlot/BoxPlotTooltip'

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

// Core types
export type {
    BarChartConfig,
    BarsConfig,
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    LineChartConfig,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    Series,
    TooltipConfig,
    TooltipContext,
    ValueDomain,
    YAxisScale,
} from './core/types'
export { DEFAULT_Y_AXIS_ID } from './core/types'

// Built-in tooltip (for reference or extension)
export { DefaultTooltip } from './overlays/DefaultTooltip'

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
export { ValueLabels } from './overlays/ValueLabels'
export type { ValueLabelsProps } from './overlays/ValueLabels'
export { AxisTitles } from './overlays/AxisTitles'
export type { AxisTitlesProps } from './overlays/AxisTitles'

// Helper for adapters that need to align with the same x-axis tick selection the chart draws.
export { computeVisibleXLabels } from './overlays/AxisLabels'

export { AnomalyPointsLayer } from './overlays/AnomalyPointsLayer'
export type { AnomalyMarker } from './overlays/AnomalyPointsLayer'
export { movingAverageKey } from './charts/TimeSeriesLineChart/utils/derived-series'

// Timeseries utils
export { createXAxisTickCallback, parseDateForAxis } from './utils/dates'
export type { TimeInterval } from './utils/dates'
export { buildYTickFormatter } from './utils/y-formatters'
export type { YAxisFormat, YFormatterConfig } from './utils/y-formatters'
export type { XAxisConfig, YAxisConfig } from './utils/use-axis-formatters'
export { buildGoalLineReferenceLines, computeSeriesNonZeroMax } from './utils/goal-lines'
export type { GoalLineConfig } from './utils/goal-lines'
export { normalizeAxisLabel } from './utils/axis-labels'

// Statistics helpers (used by trend-line / moving-average / confidence-interval features)
export { ciRanges, linearRegression, movingAverage, trendLine } from './utils/statistics'

// Generic UI primitives (no canvas) — composed alongside charts by adapters
export { Legend } from './components/Legend/Legend'
export type { LegendItem, LegendProps } from './components/Legend/Legend'
export { ChartLegend } from './components/Legend/ChartLegend'
export type { ChartLegendProps } from './components/Legend/ChartLegend'
export { legendItemsFromSeries } from './components/Legend/legendItemsFromSeries'
