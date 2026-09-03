import { CaptureImageTarget } from 'lib/components/Scenes/InsightOrDashboard/captureImageLogic'

import { DashboardTile, QueryBasedInsightModel } from '~/types'

/**
 * Marks each card with a key of its own. A dashboard renders many cards, so a capture that looked for a
 * card by class or by `data-attr` would always take the first one on the page.
 */
export const INSIGHT_CARD_KEY_ATTR = 'data-insight-card-key'

/** Keys the screenshot editor instance that the dashboard scene mounts for its tiles. */
export const DASHBOARD_TILE_SCREENSHOT_KEY = 'dashboard-tile'

export function insightCardKey(
    insight: Pick<QueryBasedInsightModel, 'short_id'>,
    tile?: Pick<DashboardTile<QueryBasedInsightModel>, 'id'>
): string {
    // The same insight can sit on a dashboard more than once, so the tile identifies the card when there is one.
    return tile?.id != null ? `tile-${tile.id}` : `insight-${insight.short_id}`
}

/**
 * Captures the whole card, not only the chart inside it: the title and the date range come with the image,
 * which is what makes a pasted tile readable on its own. The card's own controls are left out — the "⋯"
 * menu sits in the corner at all times, and a picture of a menu helps nobody.
 */
export function insightCardCaptureTarget(
    insight: Pick<QueryBasedInsightModel, 'short_id' | 'name' | 'derived_name'>,
    tile?: Pick<DashboardTile<QueryBasedInsightModel>, 'id'>
): CaptureImageTarget {
    return {
        selector: `[${INSIGHT_CARD_KEY_ATTR}="${insightCardKey(insight, tile)}"]`,
        excludeSelector: '.CardMeta__controls',
        screenshotKey: DASHBOARD_TILE_SCREENSHOT_KEY,
        name: insight.name || insight.derived_name || undefined,
    }
}
