/* oxlint-disable no-restricted-imports */
import { ChartType, DefaultDataPoint, Chart as RawChart, Tooltip, registerables } from 'chart.js'
import CrosshairPlugin from 'chartjs-plugin-crosshair'

import { inStorybookTestRunner } from 'lib/utils'

if (registerables) {
    // required for storybook to work, not found in esbuild
    RawChart.register(...registerables)
}

// Crosshair plugin can throw during cleanup if the chart never initialized its crosshair state
// (e.g. unsupported x-axis types). Guard its teardown to avoid runtime errors during destroy.
const SafeCrosshairPlugin: typeof CrosshairPlugin = {
    ...CrosshairPlugin,
    afterDestroy: (chart, args, options) => {
        if (!('crosshair' in chart) || !chart.crosshair) {
            return
        }

        CrosshairPlugin.afterDestroy?.(chart as any, args, options)
    },
}

RawChart.register(SafeCrosshairPlugin)
RawChart.defaults.animation['duration'] = 0

// Create positioner to put tooltip at cursor position
Tooltip.positioners.cursor = function (_, coordinates) {
    return coordinates
}

export class Chart<
    TType extends ChartType = ChartType,
    TData = DefaultDataPoint<TType>,
    TLabel = unknown,
> extends RawChart<TType, TData, TLabel> {
    draw(): void {
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
/* oxlint-enable no-restricted-imports */
