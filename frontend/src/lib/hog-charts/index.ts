// Components
export { BarChart } from './charts/BarChart'
export type { BarChartProps } from './charts/BarChart'
export { LineChart } from './charts/LineChart'
export type { LineChartProps } from './charts/LineChart'
export { TimeSeriesLineChart } from './timeseries/TimeSeriesLineChart'
export type { TimeSeriesLineChartConfig, TimeSeriesLineChartProps } from './timeseries/TimeSeriesLineChart'

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
