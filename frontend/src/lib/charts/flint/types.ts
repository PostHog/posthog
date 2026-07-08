import type { ChartWarning } from 'flint-chart/core'

import type { BarChartConfig, LineChartConfig, PieChartConfig, Series } from '@posthog/quill-charts'

/** Metadata every assembled spec carries, mirroring the underscore-prefixed
 *  hints Flint's Vega-Lite / ECharts / Chart.js backends attach to their output. */
export interface QuillSpecMeta {
    _warnings?: ChartWarning[]
    /** Layout-derived size hints (px). Quill computes its own layout from the
     *  container, so these are suggestions for the host, not requirements. */
    _width?: number
    _height?: number
    _dataLength?: number
}

export interface QuillBarChartSpec extends QuillSpecMeta {
    component: 'BarChart'
    series: Series[]
    labels: string[]
    config: BarChartConfig
}

export interface QuillLineChartSpec extends QuillSpecMeta {
    component: 'LineChart'
    series: Series[]
    labels: string[]
    config: LineChartConfig
}

export interface QuillPieChartSpec extends QuillSpecMeta {
    component: 'PieChart'
    series: Series[]
    config: PieChartConfig
}

/** The "native spec" of the quill backend: which quill-charts component to
 *  render and the exact props to render it with. The quill analog of the
 *  Chart.js config object `assembleChartjs()` returns. */
export type QuillChartSpec = QuillBarChartSpec | QuillLineChartSpec | QuillPieChartSpec
