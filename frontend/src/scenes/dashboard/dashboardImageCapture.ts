/**
 * Marks the grid that holds the dashboard tiles. The browser-side image capture finds the dashboard
 * this way, so treat the value as a wire string and do not rename it.
 */
export const DASHBOARD_CONTENT_DATA_ATTR = 'dashboard-image-capture'

export const DASHBOARD_CONTENT_SELECTOR = `[data-attr="${DASHBOARD_CONTENT_DATA_ATTR}"]`

/** Keys the screenshot editor instance for dashboard captures. No editor is mounted yet, so the edit action stays hidden. */
export const DASHBOARD_SCREENSHOT_KEY = 'dashboard'
