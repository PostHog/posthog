/**
 * Marks the card holding the chart and its legend. Playwright and the image capture actions both find
 * the results this way, so treat the value as a wire string and do not rename it.
 */
export const INSIGHT_GRAPH_DATA_ATTR = 'insights-graph'

export const INSIGHT_GRAPH_SELECTOR = `[data-attr="${INSIGHT_GRAPH_DATA_ATTR}"]`

/** Keys the screenshot editor instance that the insight scene mounts. */
export const INSIGHT_SCREENSHOT_KEY = 'insight'
