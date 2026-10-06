import { combineUrl, router } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { ANALYTICS_BACK_NAME } from './analyticsUtils'

/**
 * The URL with the "way back" carried along, so a page reached from Analytics sends the person back there.
 *
 * A create flow moves through several URLs (the "new" page, then the saved item), so each hop keeps the
 * `backUrl` it was given. A hop that starts on an Analytics page itself names that page as the way back.
 * Anywhere else the URL is returned as is, and the destination falls back to its own list.
 */
export function withBackLink(url: string): string {
    const { location, searchParams } = router.values
    const current = removeProjectIdIfPresent(location.pathname)
    if (typeof searchParams.backUrl === 'string' && searchParams.backUrl) {
        return combineUrl(url, {
            backUrl: searchParams.backUrl,
            backName: typeof searchParams.backName === 'string' ? searchParams.backName : ANALYTICS_BACK_NAME,
        }).url
    }
    if (current === urls.analytics() || current.startsWith(`${urls.analytics()}/`)) {
        return combineUrl(url, { backUrl: `${current}${location.search}`, backName: ANALYTICS_BACK_NAME }).url
    }
    return url
}
