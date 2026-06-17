import type { Decorator } from '@storybook/react'

import { inStorybookTestRunner } from 'lib/utils/dom'

// Body class read by buildTheme() to set ChartTheme.skipDraw.
const SKIP_CHART_CANVAS_CLASS = 'storybook-skip-chart-canvas'

/**
 * Suppresses quill-charts canvas painting in snapshots for stories that set
 * `testOptions.skipCanvasDraw` — quill charts paint asynchronously, so full-scene snapshots can
 * race the draw and flake. Only active under the test runner; interactive Storybook always draws.
 */
export const withChartCanvasSnapshot: Decorator = (Story, { parameters }) => {
    const skip = inStorybookTestRunner() && !!parameters.testOptions?.skipCanvasDraw
    document.body.classList.toggle(SKIP_CHART_CANVAS_CLASS, skip)

    return <Story />
}
