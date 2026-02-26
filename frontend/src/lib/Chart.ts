/* oxlint-disable no-restricted-imports */
import {
    type ChartConfiguration,
    type ChartItem,
    ChartType,
    DefaultDataPoint,
    Chart as RawChart,
    Tooltip,
    registerables,
} from 'chart.js'
import CrosshairPlugin from 'chartjs-plugin-crosshair'
import ZoomPlugin from 'chartjs-plugin-zoom'

import { inStorybookTestRunner } from 'lib/utils'

declare global {
    interface Window {
        __STORYBOOK_TEST_RUNNER_RENDER_CANVAS__?: boolean
    }
}

const STORYBOOK_CANVAS_RENDER_EVENT = 'storybook-test-runner:canvas-rendering-enabled'

if (registerables) {
    // required for storybook to work, not found in esbuild
    RawChart.register(...registerables)
}
RawChart.register(CrosshairPlugin)
RawChart.register(ZoomPlugin)
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
    private readonly onStorybookCanvasRenderingEnabled = (): void => {
        if (window.__STORYBOOK_TEST_RUNNER_RENDER_CANVAS__) {
            this.update('none')
        }
    }

    constructor(item: ChartItem, config: ChartConfiguration<TType, TData, TLabel>) {
        super(item, config)

        if (inStorybookTestRunner()) {
            window.addEventListener(STORYBOOK_CANVAS_RENDER_EVENT, this.onStorybookCanvasRenderingEnabled)
        }
    }

    destroy(): void {
        if (inStorybookTestRunner()) {
            window.removeEventListener(STORYBOOK_CANVAS_RENDER_EVENT, this.onStorybookCanvasRenderingEnabled)
        }

        super.destroy()
    }

    draw(): void {
        if (inStorybookTestRunner() && !window.__STORYBOOK_TEST_RUNNER_RENDER_CANVAS__) {
            // Disable Chart.js rendering in Storybook snapshots, as they've proven to be very flaky
            return
        }
        super.draw()

        if (inStorybookTestRunner()) {
            this.canvas?.setAttribute('data-storybook-canvas-rendered', 'true')
        }
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
