/* oxlint-disable no-restricted-imports */
import { BoxAndWiskers, BoxPlotController } from '@sgratzl/chartjs-chart-boxplot'
import { ChartType, DefaultDataPoint, Chart as RawChart, Tooltip, registerables } from 'chart.js'
import CrosshairPlugin from 'chartjs-plugin-crosshair'
import ZoomPlugin from 'chartjs-plugin-zoom'

import { inStorybookTestRunner } from 'lib/utils'

if (registerables) {
    // required for storybook to work, not found in esbuild
    RawChart.register(...registerables)
}
RawChart.register(CrosshairPlugin)
RawChart.register(ZoomPlugin)
RawChart.register(BoxPlotController, BoxAndWiskers)
RawChart.defaults.animation = false

// Create positioner to put tooltip at cursor position
Tooltip.positioners.cursor = function (_, coordinates) {
    return coordinates
}

export class Chart<
    TType extends ChartType = ChartType,
    TData = DefaultDataPoint<TType>,
    TLabel = unknown,
> extends RawChart<TType, TData, TLabel> {
    override draw(): void {
        if (inStorybookTestRunner()) {
            // Disable Chart.js rendering in Storybook snapshots, as they've proven to be very flaky
            return
        }
        super.draw()
    }
}

export type {
    ActiveElement,
    ChartConfiguration,
    ChartData,
    ChartDataset,
    ChartEvent,
    ChartItem,
    ChartOptions,
    ChartType,
    ChartTypeRegistry,
    Color,
    DefaultDataPoint,
    GridLineOptions,
    InteractionItem,
    LegendOptions,
    Plugin,
    ScaleOptions,
    ScaleOptionsByType,
    ScriptableLineSegmentContext,
    Tick,
    TickOptions,
    Tooltip,
    TooltipItem,
    TooltipModel,
    TooltipOptions,
    TooltipPositionerFunction,
} from 'chart.js'
export { defaults, registerables } from 'chart.js'

// Mirrors chart.js's internal DeepPartial (frontend/node_modules/chart.js/dist/types/utils.d.ts).
// Re-declared here because chart.js's `exports` map doesn't expose `dist/types/utils`, and
// TS 6.0's bundler resolution rejects the deep import. Kept structurally identical so it
// remains assignable to chart.js options types like `LegendOptions` (which use DeepPartial).
export type DeepPartial<T> = T extends Function
    ? T
    : T extends Array<infer U>
      ? Array<DeepPartial<U>>
      : T extends object
        ? { [P in keyof T]?: DeepPartial<T[P]> }
        : T | undefined
/* oxlint-enable no-restricted-imports */
