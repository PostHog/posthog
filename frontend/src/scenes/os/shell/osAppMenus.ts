import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsTab } from 'scenes/feature-flags/featureFlagsLogic'
import { SurveysTabs } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { getTreeItemsMetadata, getTreeItemsNew, getTreeItemsProducts } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab, ExperimentsTabs, ReplayTabs, SavedInsightsTabs } from '~/types'

import { osPathShowsPage, parseOsHref } from '../bridge/osFrameRouting'
import { osAppForPath } from '../dock/osDockItems'
import type { OsApp } from '../store/osAppCatalog'

export interface OsAppMenuItem {
    label: string
    href: string
}

export interface OsAppMenuPage extends OsAppMenuItem {
    /** Listed only while this feature flag is on, because the app shows the tab only then. */
    flag?: string
}

export interface OsAppMenu {
    app: OsApp
    /** The app's own pages, the same as the tabs the app shows. */
    pages: OsAppMenuItem[]
    /** The page the window shows, or null on a page the menu does not list, such as one insight. */
    activePage: OsAppMenuItem | null
    /** Other apps that belong with this one. They open in their own window. */
    relatedApps: OsAppMenuItem[]
    /** Things the app can create, from the product manifests. */
    newItems: OsAppMenuItem[]
}

type FeatureFlags = Record<string, boolean | string | undefined>

const tabOf = (href: string, tab: string): string => combineUrl(href, { tab }).url

/**
 * The pages of the apps that have a sub-navigation, keyed by the app's catalog key. The labels and the
 * order follow the tabs each app shows, and the first page is the tab the app opens on. A page must open
 * in the same app, so a page that another app owns (Dashboards) goes in `OS_RELATED_APPS` instead.
 */
export const OS_APP_MENU_PAGES: Record<string, OsAppMenuPage[]> = {
    'Product analytics': [
        {
            label: 'Home',
            href: urls.savedInsights(SavedInsightsTabs.Home),
            flag: FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB,
        },
        { label: 'All insights', href: urls.savedInsights(SavedInsightsTabs.All) },
        { label: 'My insights', href: urls.savedInsights(SavedInsightsTabs.Yours) },
        { label: 'Alerts', href: urls.alerts() },
        { label: 'Notifications', href: urls.savedInsights(SavedInsightsTabs.Notifications) },
        { label: 'History', href: urls.savedInsights(SavedInsightsTabs.History) },
    ],
    'Web analytics': [
        { label: 'Web analytics', href: urls.webAnalytics() },
        { label: 'Web vitals', href: urls.webAnalyticsWebVitals() },
        { label: 'Page reports', href: urls.webAnalyticsPageReports() },
        { label: 'Live', href: urls.webAnalyticsLive() },
        { label: 'Installation health', href: urls.webAnalyticsHealth() },
    ],
    'Session replay': [
        { label: 'Recordings', href: urls.replay(ReplayTabs.Home) },
        { label: 'Collections', href: urls.replay(ReplayTabs.Playlists) },
        { label: 'Comments', href: urls.replay(ReplayTabs.Comments) },
        { label: 'Filter templates', href: urls.replay(ReplayTabs.Templates) },
        { label: 'Settings', href: urls.replaySettings() },
    ],
    'Feature flags': [
        { label: 'Overview', href: urls.featureFlags() },
        { label: 'Projects', href: urls.featureFlags(FeatureFlagsTab.PROJECTS) },
        { label: 'History', href: urls.featureFlags(FeatureFlagsTab.HISTORY) },
    ],
    Experiments: [
        { label: 'Experiments', href: urls.experiments() },
        { label: 'Shared metrics', href: tabOf(urls.experiments(), ExperimentsTabs.SharedMetrics) },
        { label: 'Holdout groups', href: tabOf(urls.experiments(), ExperimentsTabs.Holdouts) },
        { label: 'History', href: tabOf(urls.experiments(), ExperimentsTabs.History) },
        { label: 'Settings', href: tabOf(urls.experiments(), ExperimentsTabs.Settings) },
    ],
    Surveys: [
        { label: 'Active', href: urls.surveys() },
        { label: 'Archived', href: urls.surveys(SurveysTabs.Archived) },
        { label: 'Notifications', href: urls.surveys(SurveysTabs.Notifications) },
        { label: 'History', href: urls.surveys(SurveysTabs.History) },
        { label: 'Settings', href: urls.surveys(SurveysTabs.Settings) },
    ],
    'Error tracking': [
        { label: 'Issues', href: urls.errorTracking() },
        { label: 'Insights', href: urls.errorTracking({ activeTab: 'insights' }) },
        { label: 'Configuration', href: urls.errorTrackingConfiguration() },
    ],
    'system:activity': [
        { label: 'Events', href: urls.activity(ActivityTab.ExploreEvents) },
        { label: 'Sessions', href: urls.activity(ActivityTab.ExploreSessions) },
        { label: 'Live', href: urls.activity(ActivityTab.LiveEvents) },
    ],
    'system:settings': [
        { label: 'Project', href: urls.settings('project') },
        { label: 'Organization', href: urls.settings('organization') },
        { label: 'Account', href: urls.settings('user') },
    ],
}

/** Apps that belong with another app, keyed by that app's catalog key. */
const OS_RELATED_APPS: Record<string, string[]> = {
    'Product analytics': ['Dashboards'],
}

/**
 * The listed page a window shows. When several match, the page with the longest query wins, so
 * `?tab=history` beats the page without a tab. A URL without the tab key shows the tab the app opens
 * on, which is the first page with that path.
 */
function activePageOf(path: string, pages: OsAppMenuItem[]): OsAppMenuItem | null {
    let best: OsAppMenuItem | null = null
    let bestParams = -1
    for (const page of pages) {
        const params = [...parseOsHref(page.href).params.keys()].length
        if (osPathShowsPage(path, page.href) && params > bestParams) {
            best = page
            bestParams = params
        }
    }
    if (best) {
        return best
    }
    const current = parseOsHref(path)
    return (
        pages.find((page) => {
            const { pathname, params } = parseOsHref(page.href)
            return pathname === current.pathname && [...params.keys()].every((key) => !current.params.has(key))
        }) ?? null
    )
}

function itemName(item: FileSystemImport): string {
    return item.displayLabel || unescapePath(splitPath(item.path).pop() ?? item.path)
}

/** What the app can create: the manifests' "new" items that open one of the app's scenes. */
function newItemsOf(app: OsApp, featureFlags: FeatureFlags): OsAppMenuItem[] {
    const treeItem = [...getTreeItemsProducts(), ...getTreeItemsMetadata()].find((item) => item.path === app.key)
    const sceneKeys = new Set(treeItem?.sceneKeys ?? [])
    if (!treeItem || sceneKeys.size === 0) {
        return []
    }
    return getTreeItemsNew()
        .filter(
            (item) =>
                !!item.href &&
                (!item.flag || !!featureFlags[item.flag]) &&
                ((item.sceneKeys ?? []).some((key) => sceneKeys.has(key)) ||
                    (!!item.type && item.type === treeItem.type))
        )
        .sort((a, b) => (a.visualOrder ?? Infinity) - (b.visualOrder ?? Infinity))
        .map((item) => ({ label: itemName(item).replace(/^New /, ''), href: item.href as string }))
}

function pagesOf(app: OsApp, featureFlags: FeatureFlags): OsAppMenuPage[] | undefined {
    return OS_APP_MENU_PAGES[app.key]?.filter((page) => !page.flag || !!featureFlags[page.flag])
}

/**
 * The links each app claims pages with: its own link and every page its menu lists. The dock and the
 * menu bar both resolve a window's app from these, so they agree on it.
 */
export function osAppClaims(apps: OsApp[], featureFlags: FeatureFlags): OsApp[] {
    return apps.flatMap((app) => [
        app,
        ...(pagesOf(app, featureFlags) ?? []).map((page): OsApp => ({ ...app, href: page.href })),
    ])
}

/**
 * The menu of the app a window shows, or null when no app claims the window's path. An app claims its
 * own link and every page it lists, and the longest match wins (see `osAppForPath`). Only the apps in
 * `apps` claim pages, so an app behind a feature flag that is off, or without access, gets no menu.
 * `previousKey` is the app the window showed before, for a page that several apps could claim.
 */
export function osAppMenuFor(
    path: string | null,
    apps: OsApp[],
    featureFlags: FeatureFlags,
    previousKey?: string
): OsAppMenu | null {
    if (!path) {
        return null
    }
    const claims = osAppClaims(apps, featureFlags)
    const ownerKey = (href: string, previous?: string): string | null =>
        osAppForPath(href, claims, previous)?.key ?? null
    const app = apps.find((candidate) => candidate.key === ownerKey(path, previousKey))
    if (!app) {
        return null
    }
    const pages = pagesOf(app, featureFlags) ?? [{ label: app.name, href: app.href }]
    return {
        app,
        pages,
        activePage: activePageOf(path, pages),
        relatedApps: (OS_RELATED_APPS[app.key] ?? []).flatMap((key) => {
            const related = apps.find((candidate) => candidate.key === key)
            return related ? [{ label: related.name, href: related.href }] : []
        }),
        // A "new" item that opens another app, such as a new SQL insight, would move this window to that app.
        newItems: newItemsOf(app, featureFlags).filter((item) => ownerKey(item.href) === app.key),
    }
}
