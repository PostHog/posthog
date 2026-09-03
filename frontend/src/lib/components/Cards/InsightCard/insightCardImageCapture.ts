import { CaptureImageTarget } from 'lib/components/Scenes/InsightOrDashboard/captureImageLogic'

import { DashboardTile, QueryBasedInsightModel } from '~/types'

/**
 * Marks each card with a key of its own. A dashboard renders many cards, so a capture that looked for a
 * card by class or by `data-attr` would always take the first one on the page.
 */
export const INSIGHT_CARD_KEY_ATTR = 'data-insight-card-key'

/**
 * Keys the screenshot editor instance that a dashboard mounts for its tiles. One page can hold several
 * dashboards — a notebook with dashboard widgets, a feature flag's dashboard — and editors sharing a key
 * share their open state, so the key is per dashboard.
 */
export function dashboardTileScreenshotKey(dashboardId?: number | null): string {
    return `dashboard-tile-${dashboardId ?? 'standalone'}`
}

/** The card's own chrome: the controls in the corner, the resize handles, and the grid's own handles. */
const CARD_CHROME_SELECTOR = '.CardMeta__controls, .handle, .react-resizable-handle'

export function insightCardKey(
    insight: Pick<QueryBasedInsightModel, 'short_id'>,
    tile?: Pick<DashboardTile<QueryBasedInsightModel>, 'id'>
): string {
    // The same insight can sit on a dashboard more than once, so the tile identifies the card when there is one.
    return tile?.id != null ? `tile-${tile.id}` : `insight-${insight.short_id}`
}

/**
 * Captures the whole card, not only the chart inside it: the heading comes with the image, which is what
 * makes a pasted tile readable on its own. A compact tile shows its date range only when it overrides the
 * dashboard's, so the dashboard's own range stays outside the picture. The card's chrome is left out — the
 * "⋯" menu sits in the corner at all times, and a picture of a menu helps nobody.
 */
export function insightCardCaptureTarget(
    insight: Pick<QueryBasedInsightModel, 'short_id' | 'name' | 'derived_name'>,
    tile?: Pick<DashboardTile<QueryBasedInsightModel>, 'id'>,
    dashboardId?: number | null
): CaptureImageTarget {
    return {
        selector: `[${INSIGHT_CARD_KEY_ATTR}="${insightCardKey(insight, tile)}"]`,
        excludeSelector: CARD_CHROME_SELECTOR,
        screenshotKey: dashboardTileScreenshotKey(dashboardId),
        name: insight.name || insight.derived_name || undefined,
    }
}
