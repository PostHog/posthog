import type { TooltipPositionerFunction } from 'lib/Chart'

declare module 'chart.js' {
    // Extend tooltip positioner map
    interface TooltipPositionerMap {
        cursor: TooltipPositionerFunction<ChartType>
    }
}
