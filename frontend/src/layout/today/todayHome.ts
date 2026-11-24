import { FeatureFlagKey, FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isUnderPath } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { getNavProductPages } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { isTodayHomePaneEnabled, isTodayPaneEnabled } from './todayPaneFlags'
import { TodayPaneProduct, paneProductForPath, shownPaneProducts } from './todayPaneProducts'

interface TodayHomeRowSpec {
    // pinned: part of the row's `data-attr`.
    key: string
    label: string
    href: string
    /**
     * The navigation page the row borrows its icon, hover card and flag from. The Inbox tabs are not navigation
     * pages of their own, so their rows borrow the Inbox page and show only when the Products pane shows it.
     */
    navHref: string
    requiredFlags?: FeatureFlagKey[]
    section?: string
}

function homeTopSpecs(): TodayHomeRowSpec[] {
    return [
        { key: 'today', label: 'Today', href: urls.projectHomepage(), navHref: urls.projectRoot(), section: '/' },
        { key: 'inbox-reports', label: 'Inbox reports', href: urls.inbox('reports'), navHref: urls.inbox() },
        {
            key: 'inbox-monitoring',
            label: 'Monitoring',
            href: urls.inbox('monitoring'),
            navHref: urls.inbox(),
            requiredFlags: [FEATURE_FLAGS.SIGNALS_REPORT_MONITORING],
        },
        { key: 'pulse', label: 'Pulse', href: urls.pulse(), navHref: urls.pulse() },
    ]
}

function homeBottomSpecs(): TodayHomeRowSpec[] {
    return [{ key: 'inbox-settings', label: 'Inbox settings', href: urls.inbox('settings'), navHref: urls.inbox() }]
}

function homeRows(pages: FileSystemImport[], specs: TodayHomeRowSpec[]): TodayPaneProduct[] {
    return specs.flatMap(({ key, label, href, navHref, section }) => {
        const item = pages.find((page) => page.href === navHref)
        return item ? [{ key, label, href, item, matchPaths: [href, ...(section ? [section] : [])] }] : []
    })
}

function shownHomeRows(
    pages: FileSystemImport[],
    specs: TodayHomeRowSpec[],
    featureFlags: FeatureFlagsSet
): TodayPaneProduct[] {
    const flagged = specs.filter((spec) => (spec.requiredFlags ?? []).every((flag) => !!featureFlags[flag]))
    return shownPaneProducts(homeRows(pages, flagged), featureFlags)
}

export interface HomeProducts {
    top: TodayPaneProduct[]
    bottom: TodayPaneProduct[]
}

export function homeItems(featureFlags: FeatureFlagsSet): HomeProducts {
    const pages = getNavProductPages()
    return {
        top: shownHomeRows(pages, homeTopSpecs(), featureFlags),
        bottom: shownHomeRows(pages, homeBottomSpecs(), featureFlags),
    }
}

export function homeProductForPath(path: string): TodayPaneProduct | undefined {
    return paneProductForPath(homeRows(getNavProductPages(), [...homeTopSpecs(), ...homeBottomSpecs()]), path)
}

export function isHomePanePath(path: string): boolean {
    return (
        path === urls.inbox() ||
        isUnderPath(path, urls.inbox('reports')) ||
        isUnderPath(path, urls.inbox('monitoring')) ||
        isUnderPath(path, urls.pulse())
    )
}

/** Inbox sources belong to Data, so they open it only while the Data pane is on as well. */
export function homePaneRouteForPath(path: string, featureFlags: FeatureFlagsSet): 'home' | 'data' | null {
    if (!isTodayHomePaneEnabled(featureFlags)) {
        return null
    }
    if (isHomePanePath(path)) {
        return 'home'
    }
    return isTodayPaneEnabled('data', featureFlags) && isUnderPath(path, urls.inbox('sources')) ? 'data' : null
}
