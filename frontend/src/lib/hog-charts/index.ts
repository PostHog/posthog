// Components
export { BarChart } from './charts/BarChart'
export type { BarChartProps } from './charts/BarChart'
export { LineChart } from './charts/LineChart'
export type { LineChartProps } from './charts/LineChart'
export { TimeSeriesLineChart } from './charts/TimeSeriesLineChart'
export type { TimeSeriesLineChartConfig, TimeSeriesLineChartProps } from './charts/TimeSeriesLineChart'

// Base chart (for building new chart types)
export { Chart } from './core/Chart'
export type { ChartProps } from './core/Chart'
export { DEFAULT_MARGINS } from './core/hooks/useChartMargins'

// Chart context (for custom overlay children)
export { useChart, useChartHover, useChartLayout } from './core/chart-context'
export type { BaseChartContext, ChartHoverContextValue, ChartLayoutContextValue } from './core/chart-context'

// Core types
export type {
    BarChartConfig,
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
    TooltipContext,
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

// Helper for adapters that need to align with the same x-axis tick selection the chart draws.
export { computeVisibleXLabels } from './overlays/AxisLabels'

// Timeseries overlays
export { AnnotationsLayer } from './overlays/AnnotationsLayer'
export { AnomalyPointsLayer } from './overlays/AnomalyPointsLayer'

// Timeseries utils
export { createXAxisTickCallback, parseDateForAxis } from './charts/TimeSeriesLineChart/utils/dates'
export {
    alertThresholdsToReferenceLines,
    computeSeriesNonZeroMax,
    goalLinesToReferenceLines,
} from './charts/TimeSeriesLineChart/utils/goalLinesAdapter'

// Timeseries derived series
export {
    buildMainTrendsSeries,
    buildTrendsChartConfig,
    buildTrendsSeries,
} from './charts/TimeSeriesLineChart/derived-series'
export type {
    BuildTrendsChartConfigOpts,
    BuildTrendsSeriesOpts,
    BuiltTrendsSeries,
    TrendsResultLike,
} from './charts/TimeSeriesLineChart/derived-series'
