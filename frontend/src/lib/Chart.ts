import {
    ActiveElement,
    Chart,
    ChartDataset,
    ChartEvent,
    ChartItem,
    ChartOptions,
    ChartType,
    Color,
    GridLineOptions,
    InteractionItem,
    Plugin,
    registerables,
    ScriptableLineSegmentContext,
    TickOptions,
    Tooltip,
    TooltipModel,
    TooltipOptions,
} from 'chart.js'
import CrosshairPlugin from 'chartjs-plugin-crosshair'

if (registerables) {
    // required for storybook to work, not found in esbuild
    Chart.register(...registerables)
}
Chart.register(CrosshairPlugin)

// Disable animations by default
Chart.defaults.animation['duration'] = 0

// Create positioner to put tooltip at cursor position
Tooltip.positioners.cursor = function (_, coordinates) {
    return coordinates
}

export { Chart }

export type {
    ActiveElement,
    ChartDataset,
    ChartEvent,
    ChartItem,
    ChartOptions,
    ChartType,
    Color,
    GridLineOptions,
    InteractionItem,
    Plugin,
    ScriptableLineSegmentContext,
    TickOptions,
    TooltipModel,
    TooltipOptions,
}
