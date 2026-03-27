// Components
export { LineChart } from './components/LineChart'
export type { LineChartProps } from './components/LineChart'

// Core types
export type { ChartDimensions, ChartMargins, GoalLine, PointClickData, Series, TooltipContext } from './core/types'

// Scales
export { autoFormatYTick, computePercentStackData, createScales, createXScale, createYScale } from './core/scales'

// Interaction
export { buildPointClickData, buildTooltipContext, findNearestIndex, linearRegression } from './core/interaction'

// Canvas rendering
export { drawArea, drawGrid, drawHighlightPoint, drawLine, drawPoints } from './core/canvas-renderer'

// Overlays
export { AxisLabels } from './overlays/AxisLabels'
export { Crosshair } from './overlays/Crosshair'
export { DataLabels } from './overlays/DataLabels'
export { GoalLines } from './overlays/GoalLines'
export { Tooltip } from './overlays/Tooltip'
export { TrendLine } from './overlays/TrendLine'
export { ZoomBrush } from './overlays/ZoomBrush'
