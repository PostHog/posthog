import { combineUrl, router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { ANALYTICS_BACK_NAME } from './analyticsUtils'

export interface AnalyticsBackLink {
    url: string
    name: string
}

function isAnalyticsPath(path: string): boolean {
    return path === urls.analytics() || path.startsWith(`${urls.analytics()}/`)
}

/**
 * The way back an Analytics page left in the URL, or null when the URL holds none to trust.
 *
 * Other pages write `backUrl` too (a flag's usage dashboard, the accounts list), and anyone can type one.
 * Only a relative link under the Analytics pages counts, and only while the pane exists for this person,
 * so a shared address bar never sends a colleague without the flag to a missing page or off the app.
 */
export function analyticsBackLink(
    searchParams: Record<string, unknown>,
    featureFlags: Record<string, unknown>
): AnalyticsBackLink | null {
    const backUrl = searchParams.backUrl
    if (typeof backUrl !== 'string' || !backUrl.startsWith('/') || backUrl.startsWith('//')) {
        return null
    }
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]) {
        return null
    }
    if (!isAnalyticsPath(removeProjectIdIfPresent(backUrl.split(/[?#]/)[0]))) {
        return null
    }
    const backName = searchParams.backName
    return { url: backUrl, name: typeof backName === 'string' && backName ? backName : ANALYTICS_BACK_NAME }
}

/**
 * The URL with the way back carried along, so a page reached from Analytics sends the person back there.
 *
 * A create flow moves through several URLs (the "new" page, then the saved item), so each hop keeps an
 * Analytics link it was given. A hop that starts on an Analytics page names that page as the way back.
 * Anywhere else the URL is returned as is, and the destination falls back to its own list.
 */
export function withBackLink(url: string): string {
    const { location, searchParams } = router.values
    const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags ?? {}
    const current = removeProjectIdIfPresent(location.pathname)
    const carried = analyticsBackLink(searchParams, featureFlags)
    if (carried) {
        return combineUrl(url, { backUrl: carried.url, backName: carried.name }).url
    }
    if (featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] && isAnalyticsPath(current)) {
        return combineUrl(url, { backUrl: `${current}${location.search}`, backName: ANALYTICS_BACK_NAME }).url
    }
    return url
}

/** The two params that carry an Analytics back link, for a page that rebuilds its own URL and must keep them. */
export function backLinkParams(
    searchParams: Record<string, unknown>
): { backUrl: string; backName: string } | undefined {
    const link = analyticsBackLink(searchParams, featureFlagLogic.findMounted()?.values.featureFlags ?? {})
    return link ? { backUrl: link.url, backName: link.name } : undefined
}
