// Components
export { LineChart } from './components/LineChart'
export type { LineChartProps } from './components/LineChart'

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
    GoalLine,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipContext,
} from './core/types'

// Built-in tooltip (for reference or extension)
export { DefaultTooltip } from './overlays/DefaultTooltip'
