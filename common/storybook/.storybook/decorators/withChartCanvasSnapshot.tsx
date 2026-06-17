import type { Decorator } from '@storybook/react'

import { inStorybookTestRunner } from 'lib/utils/dom'

/** Body class read by the app's `buildTheme()` to set `ChartTheme.skipDraw`. */
const SKIP_CHART_CANVAS_CLASS = 'storybook-skip-chart-canvas'

/**
 * Global story decorator that suppresses quill-charts canvas painting in visual snapshots.
 *
 * quill charts paint asynchronously (ResizeObserver → requestAnimationFrame), so in full-scene
 * stories the screenshot can land before the chart draws — producing flaky empty-vs-rendered
 * diffs. Stories that render a chart but aren't testing its pixels opt out of drawing via
 * `parameters.testOptions.skipCanvasDraw` (chart pixels are covered by the isolated chart stories).
 *
 * Only active under the snapshot test runner — interactive Storybook always draws charts.
 *
 * ```ts
 * export const MyScene: Story = {
 *   parameters: { testOptions: { skipCanvasDraw: true } },
 * }
 * ```
 */
export const withChartCanvasSnapshot: Decorator = (Story, { parameters }) => {
    const skip = inStorybookTestRunner() && !!parameters.testOptions?.skipCanvasDraw
    document.body.classList.toggle(SKIP_CHART_CANVAS_CLASS, skip)

    return <Story />
}
