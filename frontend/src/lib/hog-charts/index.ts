// Components
export { LineChart } from './charts/LineChart'
export type { LineChartProps } from './charts/LineChart'

// Base chart (for building new chart types)
export { Chart } from './core/Chart'
export type { ChartProps } from './core/Chart'

// Chart context (for custom overlay children)
export { useChart } from './core/chart-context'
export type { BaseChartContext } from './core/chart-context'

// Core types
export type {
    ChartConfig,
    ChartDrawArgs,
    ChartScales,
    CreateScalesFn,
    LineChartConfig,
    PointClickData,
    ResolveValueFn,
    Series,
    TooltipContext,
} from './core/types'

// Built-in tooltip (for reference or extension)
export { DefaultTooltip } from './overlays/DefaultTooltip'
