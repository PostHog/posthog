/* oxlint-disable no-restricted-imports */
import 'chartjs-adapter-dayjs-3'

import { BoxAndWiskers, BoxPlotController } from '@sgratzl/chartjs-chart-boxplot'
import { ChartType, DefaultDataPoint, Chart as RawChart, Tooltip, registerables } from 'chart.js'
import CrosshairPlugin from 'chartjs-plugin-crosshair'
import ZoomPlugin from 'chartjs-plugin-zoom'

import { inStorybookTestRunner } from 'lib/utils/dom'

if (registerables) {
    // required for storybook to work, not found in esbuild
    RawChart.register(...registerables)
}
RawChart.register(CrosshairPlugin)
RawChart.register(ZoomPlugin)
RawChart.register(BoxPlotController, BoxAndWiskers)
RawChart.defaults.animation = false

// Clamp the device-pixel ratio chart.js uses to back its canvas. Its `retinaScale` multiplies
// cssWidth × cssHeight by this ratio, and on a large chart with a high devicePixelRatio (3+) the
// product can exceed the browser's max canvas size — the allocation then throws
// "Canvas exceeds max size". Capping at 2 keeps charts crisp on retina displays while bounding the
// backing store; charts narrower than ~8000px CSS stay within the limit at any real viewport.
RawChart.defaults.devicePixelRatio = Math.min(typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1, 2)

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

// DeepPartial implementation taken from the utility-types NPM package, which is
// Copyright (c) 2016 Piotr Witek <piotrek.witek@gmail.com> (http://piotrwitek.github.io)
// and used under the terms of the MIT license
export type DeepPartial<T> = T extends Function
    ? T
    : T extends Array<infer U>
      ? _DeepPartialArray<U>
      : T extends object
        ? _DeepPartialObject<T>
        : T | undefined

type _DeepPartialArray<T> = Array<DeepPartial<T>>
type _DeepPartialObject<T> = { [P in keyof T]?: DeepPartial<T[P]> }
/* oxlint-enable no-restricted-imports */
