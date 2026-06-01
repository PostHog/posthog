// Components
export { BarChart } from './charts/BarChart'
export type { BarChartProps } from './charts/BarChart'
export { LineChart } from './charts/LineChart'
export type { LineChartProps } from './charts/LineChart'
export { TimeSeriesLineChart } from './charts/TimeSeriesLineChart/TimeSeriesLineChart'
export type {
    ConfidenceIntervalConfig,
    MovingAverageConfig,
    TimeSeriesLineChartConfig,
    TimeSeriesLineChartProps,
    TrendLineConfig,
    ValueLabelsConfig,
} from './charts/TimeSeriesLineChart/TimeSeriesLineChart'
export type { InProgressConfig } from './charts/TimeSeriesLineChart/utils/in-progress'

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
    TooltipConfig,
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
export { AnomalyPointsLayer } from './charts/TimeSeriesLineChart/overlays/AnomalyPointsLayer'
export type { AnomalyMarker } from './charts/TimeSeriesLineChart/overlays/AnomalyPointsLayer'
export { movingAverageKey } from './charts/TimeSeriesLineChart/utils/derived-series'

// Timeseries utils
export { createXAxisTickCallback, parseDateForAxis } from './charts/TimeSeriesLineChart/utils/dates'
export type { TimeInterval } from './charts/TimeSeriesLineChart/utils/dates'
export { buildYTickFormatter } from './charts/TimeSeriesLineChart/utils/y-formatters'
export type { YAxisFormat, YFormatterConfig } from './charts/TimeSeriesLineChart/utils/y-formatters'
export type { XAxisConfig, YAxisConfig } from './charts/TimeSeriesLineChart/utils/use-axis-formatters'
export { buildGoalLineReferenceLines, computeSeriesNonZeroMax } from './charts/TimeSeriesLineChart/utils/goal-lines'
export type { GoalLineConfig } from './charts/TimeSeriesLineChart/utils/goal-lines'
