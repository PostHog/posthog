import type { TooltipPositionerFunction } from '@posthog/visualizations/Chart'

declare module 'chart.js' {
    // Extend tooltip positioner map
    interface TooltipPositionerMap {
        cursor: TooltipPositionerFunction<ChartType>
    }
}
