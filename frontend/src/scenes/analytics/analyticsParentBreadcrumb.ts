import { FEATURE_FLAGS } from 'lib/constants'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { LinkBreadcrumb } from '~/types'

import { analyticsBackLink } from './analyticsBackLink'
import { ANALYTICS_BACK_NAME } from './analyticsUtils'

/**
 * The old "Product analytics" and "Dashboards" lists are not in the Analytics navigation, so they must not be the
 * parent. Without the flag the scene keeps its old parent, `fallback`.
 */
export function analyticsParentBreadcrumb(
    searchParams: Record<string, unknown>,
    featureFlags: Record<string, unknown>,
    fallback: LinkBreadcrumb
): LinkBreadcrumb {
    const backLink = analyticsBackLink(searchParams, featureFlags)
    if (backLink) {
        return { key: backLink.url, name: backLink.name, path: backLink.url, iconType: fallback.iconType }
    }
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]) {
        return fallback
    }
    return {
        key: Scene.AnalyticsList,
        name: ANALYTICS_BACK_NAME,
        path: urls.analyticsList(),
        iconType: fallback.iconType,
    }
}
