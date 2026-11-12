import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import type { LocationChangedPayload } from 'kea-router/lib/types'
import { subscriptions } from 'kea-subscriptions'
import { windowValues } from 'kea-window-values'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isUnderPath, removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { fromPostHogProducts, isFromPostHogItem } from 'scenes/analytics/analyticsUtils'
import { libraryTypeForPath } from 'scenes/library/libraryUtils'
import { settingsSectionSceneForPath } from 'scenes/settings/settingsSectionScenes'
import { urls } from 'scenes/urls'

import type { PhaiViewMode } from '~/layout/ai/aiPanelIds'
import { aiShellLogic } from '~/layout/ai/aiShellLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { getNavProductPages, navProductHrefForPath } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { isPeopleDetailPath, isPeopleListPath } from './todayPeople'
import { todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

export type TodayRailPane = 'home' | 'spaces' | 'analytics' | 'people' | 'release' | 'products' | 'settings'

/** What the shell shows: the page, the pane picked on the rail, and whether its sidebar is open. */
export interface TodayView {
    url: string
    pane: TodayRailPane
    sidebarOpen: boolean
}

/** What showed or hid the sidebar. `navigation` is a page change that hides the unpinned sidebar. */
export type TodaySidebarToggleSource =
    | 'rail'
    | 'shortcut'
    | 'resizer'
    | 'pane_header'
    | 'scene_breadcrumb'
    | 'navigation'

export const TODAY_RAIL_WIDTH = 60
export const TODAY_PHONE_MAX_WIDTH = 768
export const TODAY_SIDEBAR_DEFAULT_WIDTH: number = 312
export const TODAY_SIDEBAR_MIN_WIDTH = 240
export const TODAY_SIDEBAR_MAX_WIDTH = 480
/** Dragging the sidebar narrower than this hides it. */
export const TODAY_SIDEBAR_CLOSE_THRESHOLD = 180

export function clampSidebarWidth(width: number | null): number {
    return Math.min(
        Math.max(Math.round(width ?? TODAY_SIDEBAR_DEFAULT_WIDTH), TODAY_SIDEBAR_MIN_WIDTH),
        TODAY_SIDEBAR_MAX_WIDTH
    )
}

/** The task composer runs on the sandbox, so the legacy view starts a chat on `/ai` instead. */
export function todayNewChatUrl(effectivePhaiView: PhaiViewMode): string {
    return effectivePhaiView === 'new' ? urls.taskNewSession() : urls.ai()
}

export const TODAY_RAIL_PANES: TodayRailPane[] = ['home', 'spaces', 'analytics', 'people', 'release', 'products']

/** The page a rail pick opens. Without one, a pick only opens the sidebar and the open page stays. */
const RAIL_PANE_HOMES: Partial<
    Record<TodayRailPane, (effectivePhaiView: PhaiViewMode, featureFlags: FeatureFlagsSet) => string>
> = {
    home: () => urls.projectHomepage(),
    spaces: todayNewChatUrl,
    analytics: () => urls.analyticsList(),
    // Not urls.customerAnalytics(): that redirect opens the Accounts page when customer-analytics-csp is on.
    people: (_, featureFlags) =>
        featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS] ? urls.customerAnalyticsDashboard() : urls.persons(),
    release: () => urls.releases(),
    settings: () => urls.settings('project'),
}

/** The page a rail pane opens, or undefined when the pane only opens the sidebar. */
export function railPaneHref(
    pane: TodayRailPane,
    effectivePhaiView: PhaiViewMode,
    featureFlags: FeatureFlagsSet
): string | undefined {
    return RAIL_PANE_HOMES[pane]?.(effectivePhaiView, featureFlags)
}

const PHONE_PAGE_LIMIT = 50

export interface TodayPhonePage {
    pathname: string
    url: string
}

export function nextPhonePages(
    pages: TodayPhonePage[],
    method: LocationChangedPayload['method'],
    page: TodayPhonePage
): TodayPhonePage[] {
    const current = pages[pages.length - 1]
    if (method === 'PUSH' && current?.pathname !== page.pathname) {
        return [...pages, page].slice(-PHONE_PAGE_LIMIT)
    }
    if (method === 'POP' && pages[pages.length - 2]?.pathname === page.pathname) {
        return [...pages.slice(0, -2), page]
    }
    return [...pages.slice(0, -1), page]
}

/** The pane a route belongs to, or null for pages that keep whichever pane was open. */
export function railPaneForPath(pathname: string): TodayRailPane | null {
    const path = removeProjectIdIfPresent(pathname)
    if (path === '/' || isUnderPath(path, urls.projectHomepage())) {
        return 'home'
    }
    if (isUnderPath(path, '/ai') || isUnderPath(path, '/spaces')) {
        return 'spaces'
    }
    if (isPeopleListPath(path) || isPeopleDetailPath(path)) {
        return 'people'
    }
    if (isUnderPath(path, '/releases')) {
        return 'release'
    }
    // Notebooks, dashboards and insights are analytics, list pages included, so they never open the Products pane.
    if (
        isUnderPath(path, urls.analytics()) ||
        isUnderPath(path, '/canvases') ||
        isUnderPath(path, urls.notebooks()) ||
        isUnderPath(path, urls.dashboards()) ||
        isUnderPath(path, '/insights') ||
        isFromPostHogItem(byPostHogItemForPath(path) ?? {})
    ) {
        return 'analytics'
    }
    if (isUnderPath(path, '/settings') || settingsSectionSceneForPath(path)) {
        return 'settings'
    }
    if (
        isUnderPath(path, urls.library()) ||
        isUnderPath(path, urls.tools()) ||
        libraryTypeForPath(path) ||
        productsPaneListsPath(path)
    ) {
        return 'products'
    }
    return null
}

let navProductPages: FileSystemImport[] | null = null

/**
 * The By PostHog entry that owns this page. Its ready-made analytics belong to Analytics. Its other pages, like
 * Session replay, belong to Products and keep an open Analytics pane open.
 */
function byPostHogItemForPath(path: string): FileSystemImport | undefined {
    const items = fromPostHogProducts().map((product) => product.item)
    // Matched like the Products tab, so a recording under /replay belongs to Session replay, not only its home page.
    const href = navProductHrefForPath(path, items)
    return href ? items.find((item) => item.href === href) : undefined
}

/** Whether the Products pane lists the product that owns this page. Some, like Dashboards, open under Analytics too. */
function productsPaneListsPath(path: string): boolean {
    navProductPages ??= getNavProductPages()
    return !!navProductHrefForPath(path, navProductPages)
}

/**
 * Whether an open Products pane stays open on this page: a product it lists, even one Analytics lists too, or any
 * People list page, so a tab like Cohorts opened from Persons does not switch the rail.
 */
function productsPaneKeepsPath(path: string, routePane: TodayRailPane | null): boolean {
    return (
        (routePane === 'analytics' && productsPaneListsPath(path)) || (routePane === 'people' && isPeopleListPath(path))
    )
}

/**
 * Whether an open Analytics pane stays open on this page: a product By PostHog lists, the SQL editor its sidebar links
 * to, or a person, group or cohort, so a drill-in from an insight does not switch the rail. Each of these opens its
 * own pane when Analytics is not showing.
 */
function analyticsPaneKeepsPath(path: string, routePane: TodayRailPane | null): boolean {
    return (
        (routePane === 'people' && isPeopleDetailPath(path)) ||
        !!byPostHogItemForPath(path) ||
        isUnderPath(path, urls.sqlEditor())
    )
}

/**
 * The pane to show after a page change. `shownPane` is the pane on screen before the change, which is the
 * route's pane when nothing was picked.
 */
function paneAfterNavigation(
    openPane: TodayRailPane | null,
    pathname: string,
    shownPane: TodayRailPane | null
): TodayRailPane | null {
    const path = removeProjectIdIfPresent(pathname)
    const routePane = railPaneForPath(pathname)
    if (openPane === 'products' && productsPaneKeepsPath(path, routePane)) {
        return openPane
    }
    if (
        shownPane === 'release' &&
        ['/feature-flags', '/experiments', '/early_access_features'].some((prefix) => isUnderPath(path, prefix))
    ) {
        return shownPane
    }
    if (shownPane === 'analytics' && analyticsPaneKeepsPath(path, routePane)) {
        return shownPane
    }
    return routePane ?? openPane
}

/** The pane to show when the app loads. The pane stored on the last visit stands in for the pane on screen before. */
function paneOnLoad(storedPane: TodayRailPane | null, pathname: string): TodayRailPane | null {
    return paneAfterNavigation(storedPane, pathname, storedPane)
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayShellLogicValues {
    effectivePhaiView: PhaiViewMode // aiShellLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    mobileLayout: boolean // navigationLogic
    activePane: TodayRailPane
    currentView: TodayView
    lastSceneUrl: string | null
    leftNavWidth: number
    mobileSidebarOpen: boolean
    onAiPage: boolean
    paneHasSidebar: boolean
    peoplePaneLinksTabs: boolean
    phoneCanGoBack: boolean
    phoneHeaderHidden: boolean
    phoneHeaderShown: boolean
    phoneLayout: boolean
    phonePages: TodayPhonePage[]
    pickedPane: TodayRailPane | null
    railPanes: TodayRailPane[]
    routePane: TodayRailPane | null
    sidebarBreadcrumbShown: boolean
    sidebarOpen: boolean
    sidebarPinned: boolean
    sidebarVisible: boolean
    sidebarWidth: number
    todayRailEnabled: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayShellLogicActions {
    locationChanged: ({
        method,
        pathname,
        search,
        searchParams,
        hash,
        hashParams,
        initial,
        url,
        routerState,
    }: LocationChangedPayload) => {
        hash: string
        hashParams: Record<string, any>
        initial: boolean
        method: 'POP' | 'PUSH' | 'REPLACE'
        pathname: string
        routerState: Record<string, any>
        search: string
        searchParams: Record<string, any>
        url: string
    } // router
    clickRailPane: (pane: TodayRailPane) => {
        pane: TodayRailPane
    }
    goBackOnPhone: () => {
        value: true
    }
    pickPane: (pane: TodayRailPane) => {
        pane: TodayRailPane
    }
    rememberSceneUrl: (location: { hash: string; pathname: string; search: string }) => {
        location: {
            hash: string
            pathname: string
            search: string
        }
    }
    restoreView: (view: TodayView) => {
        view: TodayView
    }
    setMobileSidebarOpen: (open: boolean) => {
        open: boolean
    }
    setPhonePages: (pages: TodayPhonePage[]) => {
        pages: TodayPhonePage[]
    }
    setPickedPane: (pane: TodayRailPane | null) => {
        pane: TodayRailPane | null
    }
    setSidebarOpen: (open: boolean) => {
        open: boolean
    }
    setSidebarWidth: (width: number) => {
        width: number
    }
    showPane: (pane: TodayRailPane) => {
        pane: TodayRailPane
    }
    toggleSidebar: (source: TodaySidebarToggleSource) => {
        source: TodaySidebarToggleSource
    }
    toggleSidebarPinned: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayShellLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        routePane: (location: { hash: string; pathname: string; search: string }) => TodayRailPane | null
        activePane: (
            pickedPane: TodayRailPane | null,
            routePane: TodayRailPane | null,
            featureFlags: FeatureFlagsSet
        ) => TodayRailPane
        paneHasSidebar: (activePane: TodayRailPane) => boolean
        currentView: (
            location: {
                hash: string
                pathname: string
                search: string
            },
            activePane: TodayRailPane,
            sidebarOpen: boolean
        ) => TodayView
        leftNavWidth: (
            sidebarOpen: boolean,
            sidebarWidth: number,
            mobileLayout: boolean,
            phoneLayout: boolean,
            paneHasSidebar: boolean
        ) => number
        sidebarVisible: (
            mobileLayout: boolean,
            mobileSidebarOpen: boolean,
            sidebarOpen: boolean,
            paneHasSidebar: boolean
        ) => boolean
        todayRailEnabled: (featureFlags: FeatureFlagsSet) => boolean
        railPanes: (featureFlags: FeatureFlagsSet) => TodayRailPane[]
        peoplePaneLinksTabs: (todayRailEnabled: boolean, activePane: TodayRailPane) => boolean
        onAiPage: (location: { hash: string; pathname: string; search: string }) => boolean
        phoneHeaderHidden: (
            onAiPage: boolean,
            searchParams: Record<string, any>,
            todayRailEnabled: boolean,
            phoneLayout: boolean
        ) => boolean
        phoneHeaderShown: (todayRailEnabled: boolean, phoneLayout: boolean, phoneHeaderHidden: boolean) => boolean
        phoneCanGoBack: (phonePages: TodayPhonePage[]) => boolean
        sidebarBreadcrumbShown: (
            todayRailEnabled: boolean,
            phoneLayout: boolean,
            sidebarVisible: boolean,
            paneHasSidebar: boolean
        ) => boolean
    }
}

export type todayShellLogicType = MakeLogicType<
    todayShellLogicValues,
    todayShellLogicActions,
    Record<string, any>,
    todayShellLogicMeta
>

function isAiPath(pathname: string): boolean {
    const path = removeProjectIdIfPresent(pathname)
    return path === urls.ai() || path.startsWith(`${urls.ai()}/`)
}

function sceneUrlOutsideAi(
    current: string | null,
    { pathname, search, hash }: { pathname: string; search: string; hash: string }
): string | null {
    return isAiPath(pathname) ? current : `${pathname}${search}${hash}`
}

export const todayShellLogic = kea<todayShellLogicType>([
    path(['layout', 'today', 'todayShellLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            aiShellLogic,
            ['effectivePhaiView'],
            navigationLogic,
            ['mobileLayout'],
        ],
        actions: [router, ['locationChanged']],
        logic: [todayPeopleRecentsLogic],
    })),
    actions({
        rememberSceneUrl: (location: { pathname: string; search: string; hash: string }) => ({ location }),
        pickPane: (pane: TodayRailPane) => ({ pane }),
        showPane: (pane: TodayRailPane) => ({ pane }),
        restoreView: (view: TodayView) => ({ view }),
        setPickedPane: (pane: TodayRailPane | null) => ({ pane }),
        goBackOnPhone: true,
        setPhonePages: (pages: TodayPhonePage[]) => ({ pages }),
        setMobileSidebarOpen: (open: boolean) => ({ open }),
        setSidebarOpen: (open: boolean) => ({ open }),
        setSidebarWidth: (width: number) => ({ width }),
        toggleSidebar: (source: TodaySidebarToggleSource) => ({ source }),
        toggleSidebarPinned: true,
        clickRailPane: (pane: TodayRailPane) => ({ pane }),
    }),
    windowValues(() => ({
        phoneLayout: (window: Window) => window.innerWidth < TODAY_PHONE_MAX_WIDTH,
    })),
    reducers({
        // The last pane picked on the rail, or reached through a route that belongs to one, stays open on other pages.
        // The locationChanged listener sets it after a page change, because the drill-in rule reads the previous page from the cache.
        pickedPane: [
            null as TodayRailPane | null,
            { persist: true },
            {
                showPane: (_, { pane }) => pane,
                setPickedPane: (_, { pane }) => pane,
            },
        ],
        sidebarOpen: [
            true,
            { persist: true },
            {
                setSidebarOpen: (_, { open }) => open,
            },
        ],
        sidebarPinned: [
            true,
            { persist: true },
            {
                toggleSidebarPinned: (state) => !state,
            },
        ],
        mobileSidebarOpen: [
            false,
            {
                setMobileSidebarOpen: (_, { open }) => open,
                locationChanged: () => false,
            },
        ],
        phonePages: [
            [] as TodayPhonePage[],
            {
                setPhonePages: (_, { pages }) => pages,
                setMobileSidebarOpen: (state, { open }) => (open ? [] : state),
                locationChanged: (state, { method, pathname, search, hash }) =>
                    nextPhonePages(state, method, { pathname, url: `${pathname}${search}${hash}` }),
            },
        ],
        // Where the user was before /ai, so a chat moved from /ai into the panel opens over that scene again.
        lastSceneUrl: [
            null as string | null,
            {
                locationChanged: (state, location) => sceneUrlOutsideAi(state, location),
                rememberSceneUrl: (state, { location }) => sceneUrlOutsideAi(state, location),
            },
        ],
        // The resizer persists the width itself. This copy lets the app layout size the main column from it.
        sidebarWidth: [TODAY_SIDEBAR_DEFAULT_WIDTH, { setSidebarWidth: (_, { width }) => clampSidebarWidth(width) }],
    }),
    selectors({
        routePane: [
            () => [router.selectors.location],
            (location: { pathname: string }): TodayRailPane | null => railPaneForPath(location.pathname),
        ],
        activePane: [
            (s) => [s.pickedPane, s.routePane, s.featureFlags],
            (
                pickedPane: TodayRailPane | null,
                routePane: TodayRailPane | null,
                featureFlags: FeatureFlagsSet
            ): TodayRailPane => {
                const pane = pickedPane ?? routePane ?? 'home'
                return pane === 'release' && !featureFlags[FEATURE_FLAGS.RELEASES_AREA] ? 'home' : pane
            },
        ],
        paneHasSidebar: [(s) => [s.activePane], (activePane: TodayRailPane): boolean => activePane !== 'home'],
        currentView: [
            (s) => [router.selectors.location, s.activePane, s.sidebarOpen],
            (
                location: { pathname: string; search: string; hash: string },
                activePane: TodayRailPane,
                sidebarOpen: boolean
            ): TodayView => ({
                url: `${location.pathname}${location.search}${location.hash}`,
                pane: activePane,
                sidebarOpen,
            }),
        ],
        leftNavWidth: [
            (s) => [s.sidebarOpen, s.sidebarWidth, s.mobileLayout, s.phoneLayout, s.paneHasSidebar],
            (
                sidebarOpen: boolean,
                sidebarWidth: number,
                mobileLayout: boolean,
                phoneLayout: boolean,
                paneHasSidebar: boolean
            ): number =>
                phoneLayout
                    ? 0
                    : TODAY_RAIL_WIDTH + (sidebarOpen && paneHasSidebar && !mobileLayout ? sidebarWidth : 0),
        ],
        sidebarVisible: [
            (s) => [s.mobileLayout, s.mobileSidebarOpen, s.sidebarOpen, s.paneHasSidebar],
            (
                mobileLayout: boolean,
                mobileSidebarOpen: boolean,
                sidebarOpen: boolean,
                paneHasSidebar: boolean
            ): boolean => paneHasSidebar && (mobileLayout ? mobileSidebarOpen : sidebarOpen),
        ],
        todayRailEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV],
        ],
        railPanes: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): TodayRailPane[] =>
                TODAY_RAIL_PANES.filter((pane) => pane !== 'release' || !!featureFlags[FEATURE_FLAGS.RELEASES_AREA]),
        ],
        // The People pane links every People page and tab, so those pages hide their tabs and name while it is open.
        peoplePaneLinksTabs: [
            (s) => [s.todayRailEnabled, s.activePane],
            (todayRailEnabled: boolean, activePane: TodayRailPane): boolean =>
                todayRailEnabled && activePane === 'people',
        ],
        onAiPage: [
            () => [router.selectors.location],
            (location: { pathname: string }): boolean => isAiPath(location.pathname),
        ],
        phoneHeaderHidden: [
            (s) => [s.onAiPage, router.selectors.searchParams, s.todayRailEnabled, s.phoneLayout],
            (
                onAiPage: boolean,
                searchParams: Record<string, any>,
                todayRailEnabled: boolean,
                phoneLayout: boolean
            ): boolean => todayRailEnabled && phoneLayout && onAiPage && !!searchParams.task,
        ],
        // The phone header shows the scene title, so the scene title row leaves it out.
        phoneHeaderShown: [
            (s) => [s.todayRailEnabled, s.phoneLayout, s.phoneHeaderHidden],
            (todayRailEnabled: boolean, phoneLayout: boolean, phoneHeaderHidden: boolean): boolean =>
                todayRailEnabled && phoneLayout && !phoneHeaderHidden,
        ],
        phoneCanGoBack: [(s) => [s.phonePages], (phonePages: TodayPhonePage[]): boolean => phonePages.length > 1],
        // The scene title row names the hidden sidebar's pane, so a click there opens it again. A floating sidebar
        // covers the button instead of replacing it, so it stays and the title never shifts. Phones open the
        // sidebar from the phone header.
        sidebarBreadcrumbShown: [
            (s) => [s.todayRailEnabled, s.phoneLayout, s.sidebarVisible, s.paneHasSidebar],
            (
                todayRailEnabled: boolean,
                phoneLayout: boolean,
                sidebarVisible: boolean,
                paneHasSidebar: boolean
            ): boolean =>
                // A hidden sidebar needs the crumb to come back, docked or overlay. The phone header has its own.
                todayRailEnabled && paneHasSidebar && !phoneLayout && !sidebarVisible,
        ],
    }),
    subscriptions(({ actions }) => ({
        mobileLayout: () => actions.setMobileSidebarOpen(false),
    })),
    listeners(({ actions, values, cache }) => ({
        toggleSidebar: ({ source }) => {
            if (values.mobileLayout) {
                actions.setMobileSidebarOpen(!values.mobileSidebarOpen)
            } else {
                actions.setSidebarOpen(!values.sidebarOpen)
            }
            // pinned: analytics event name and properties. Renaming them breaks dashboards.
            posthog.capture('today sidebar toggled', {
                source,
                open: values.sidebarVisible,
                mobile_layout: values.mobileLayout,
            })
        },
        locationChanged: ({ method, pathname }) => {
            const { pickedPane } = values
            const shownPane = pickedPane ?? railPaneForPath(cache.lastPathname ?? '')
            actions.setPickedPane(paneAfterNavigation(pickedPane, pathname, shownPane))
            const pageChanged = method === 'PUSH' && pathname !== cache.lastPathname
            cache.lastPathname = pathname
            // An unpinned sidebar gives the new page room. The drawer closes on its own, and a rail pick wants it open.
            if (
                pageChanged &&
                !values.sidebarPinned &&
                !values.mobileLayout &&
                values.sidebarOpen &&
                !cache.pickingPane
            ) {
                actions.toggleSidebar('navigation')
            }
        },
        toggleSidebarPinned: () => {
            // pinned: analytics event name and property. Renaming them breaks dashboards.
            posthog.capture('today sidebar pin toggled', { pinned: values.sidebarPinned })
        },
        setMobileSidebarOpen: ({ open }) => {
            if (!open) {
                cache.disposables.dispose('drawerEscape')
                return
            }
            cache.disposables.add(() => {
                const onKeyDown = (event: KeyboardEvent): void => {
                    if (event.key === 'Escape' && values.mobileSidebarOpen) {
                        actions.setMobileSidebarOpen(false)
                    }
                }
                window.addEventListener('keydown', onKeyDown)
                return () => window.removeEventListener('keydown', onKeyDown)
            }, 'drawerEscape')
        },
        goBackOnPhone: () => {
            const previous = values.phonePages[values.phonePages.length - 2]
            if (!previous) {
                actions.setMobileSidebarOpen(true)
                return
            }
            actions.setPhonePages(values.phonePages.slice(0, -1))
            router.actions.replace(previous.url)
        },
        clickRailPane: ({ pane }) => {
            if (values.activePane === pane && values.sidebarVisible) {
                actions.toggleSidebar('rail')
                return
            }
            actions.pickPane(pane)
        },
        pickPane: ({ pane }) => {
            // pinned: analytics event name and property. Renaming them breaks dashboards.
            posthog.capture('today rail pane picked', { pane, phone_layout: values.phoneLayout })
            actions.showPane(pane)
        },
        // A rail pick without the rail's analytics, for flows that move through panes themselves, such as the tour.
        showPane: ({ pane }) => {
            const href = railPaneHref(pane, values.effectivePhaiView, values.featureFlags)
            if (href) {
                cache.pickingPane = true
                router.actions.push(href)
                cache.pickingPane = false
            }
            if (values.mobileLayout) {
                actions.setMobileSidebarOpen(true)
            } else {
                actions.setSidebarOpen(true)
            }
        },
        restoreView: ({ view }) => {
            cache.pickingPane = true
            router.actions.push(view.url)
            cache.pickingPane = false
            // The page change picks a pane from the new route, so the saved pane goes back after it.
            actions.setPickedPane(view.pane)
            actions.setSidebarOpen(view.sidebarOpen)
        },
    })),
    afterMount(({ actions, values, cache }) => {
        const { pathname, search, hash } = router.values.location
        actions.setPickedPane(paneOnLoad(values.pickedPane, pathname))
        cache.lastPathname = pathname
        actions.rememberSceneUrl({ pathname, search, hash })
        actions.setPhonePages([{ pathname, url: `${pathname}${search}${hash}` }])
    }),
])
