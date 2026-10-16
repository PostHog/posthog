import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import type { LocationChangedPayload } from 'kea-router/lib/types'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { TeamPublicType, TeamType, UserType } from '~/types'

import { signalsReportsForYouRetrieve, signalsReportsRetrieve } from 'products/signals/frontend/generated/api'
import {
    TodayReportList,
    TodayReportSnapshot,
    captureTodayReportOpened,
    captureTodayReportsImpressed,
} from 'products/signals/frontend/inbox/inboxAnalytics'
import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { reportPullRequests } from 'products/signals/frontend/inbox/utils/reportPullRequests'
import type {
    BriefingApi,
    BriefingItemApi,
    BriefingItemStateEnumApi,
    HighlightItemApi,
    HighlightsApi,
} from 'products/today/frontend/generated/api.schemas'

import { TodayAskContext, todayAskPrompt } from './todayAskPrompt'
import { hasBriefingText, itemReportId } from './todayBriefingItems'
import { todayBriefingLogic } from './todayBriefingLogic'
import { EXPLORE_ITEMS, type TodayExploreItem } from './todayExploreItems'
import {
    VISIBLE_ROWS,
    briefingRows,
    forYouRows,
    reportRows,
    rowReportId,
    type TodayForYouRow,
    type TodayForYouRows,
} from './todayForYouRows'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { recentObjectsForHome } from './todayRecentObjects'
import { type TodayReportPreview, briefingItemPreview, reportPreview } from './todayReportPreviews'
import { isSampleReportId, parseSampleParam, sampleTopReports } from './todaySampleReports'
import { todayVerdictLogic } from './todayVerdictLogic'

export const TOP_REPORT_COUNT = 5
export const MORE_REPORTS_PAGE_SIZE = 20
export const RECENT_OBJECT_COUNT = 4
const RECENT_OBJECT_MORE_COUNT = 8
const CLOCK_MS = 30_000

/** Where a report was opened from, sent with the `today report opened` event. */
export type TodayReportOpenSource = 'list' | 'more'

/** Where a question to PostHog AI came from, sent with the `today ai asked` event. */
export type TodayAskSource = 'walk_through' | 'report_page'

export type TodayList = 'for_you' | 'recents'

export interface TodayReports {
    results: SignalReport[]
    /** Every report that matches the filter, including the ones past the top five. */
    count: number
}

export interface TodayMoreReports {
    exclude: string[]
    results: SignalReport[]
    count: number
    hasMore: boolean
}

/** The report a Today report page shows, read from a path such as `/project/1/home/reports/abc`. */
export function reportIdFromPath(pathname: string): string | null {
    const match = removeProjectIdIfPresent(pathname).match(/^\/home\/reports\/([^/]+)\/?$/)
    return match ? decodeURIComponent(match[1]) : null
}

export function isTodayPath(pathname: string): boolean {
    return /^\/(home(\/reports\/[^/]+)?\/?)?$/.test(removeProjectIdIfPresent(pathname))
}

export function greetingForHour(hour: number, name: string | null | undefined): string {
    const suffix = name ? `, ${name}.` : '.'
    if (hour < 5) {
        return `You’re up late${suffix}`
    }
    if (hour < 12) {
        return `Morning${suffix}`
    }
    if (hour < 17) {
        return `Afternoon${suffix}`
    }
    return `Evening${suffix}`
}

/**
 * The page shows the report as it was when it loaded, but the action-or-answer framing must follow its current
 * state: somebody can resolve the report or open a PR on it meanwhile. A failed refetch fails closed to answering.
 */
async function currentReportContext(
    report: SignalReport,
    projectId: number | string
): Promise<{ report: SignalReport; canAct: boolean }> {
    let current: SignalReport | null = null
    try {
        // The generated type is wider than the handwritten SignalReport the Inbox helpers take. See loadTopReports.
        current = (await signalsReportsRetrieve(String(projectId), report.id)) as unknown as SignalReport
    } catch {
        current = null
    }
    if (current && isActionCapableReport(report) && !isActionCapableReport(current)) {
        lemonToast.info('This report can no longer take actions, so PostHog AI will answer instead.')
    }
    return { report: current ?? report, canAct: !!current && isActionCapableReport(current) }
}

function signalReportSnapshot(report: SignalReport): TodayReportSnapshot {
    return {
        reportId: report.id,
        priority: report.priority ?? null,
        hasPr: reportPullRequests(report).length > 0,
        signalCount: report.signal_count,
        sourceProducts: report.source_products ?? [],
    }
}

function briefingItemSnapshot(item: BriefingItemApi, reportId: string): TodayReportSnapshot {
    return {
        reportId,
        priority: item.report?.priority ?? null,
        hasPr: !!item.report?.pull_request_url,
        signalCount: item.report?.signal_count ?? null,
        sourceProducts: item.source_product ? [item.source_product] : [],
    }
}

interface TodayRankedReport {
    report: TodayReportSnapshot
    rank: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayLogicValues {
    recents: FileSystemEntry[] // recentItemsModel
    recentsHasLoaded: boolean // recentItemsModel
    currentProjectId: number | string // teamLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    briefingWaiting: boolean // todayBriefingLogic
    personalBriefing: BriefingApi | null // todayBriefingLogic
    personalBriefingLoading: boolean // todayBriefingLogic
    doneHighlightKeys: string[] // todayHighlightsLogic
    forYouHighlights: HighlightItemApi[] // todayHighlightsLogic
    highlights: HighlightsApi | null // todayHighlightsLogic
    highlightsFailed: boolean // todayHighlightsLogic
    highlightsLoading: boolean // todayHighlightsLogic
    highlightsPending: boolean // todayHighlightsLogic
    highlightsWaitOver: boolean // todayHighlightsLogic
    reportStateOverrides: Record<string, BriefingItemStateEnumApi> // todayVerdictLogic
    user: UserType | null // userLogic
    askingAi: boolean
    briefingItems: BriefingItemApi[]
    canLoadMoreReports: boolean
    currentMoreReports: TodayMoreReports | null
    expandedReportRows: Record<string, boolean>
    exploreItems: TodayExploreItem[]
    forYouCanShowLess: boolean
    forYouCanShowMore: boolean
    forYouFailedNote: string | null
    forYouOpenCount: number
    forYouReady: boolean
    forYouRows: TodayForYouRows
    forYouVisibleRows: TodayForYouRow[]
    greeting: string
    homeScrollTop: number | null
    hour: number
    isNewProject: boolean
    listExpanded: Record<TodayList, boolean>
    loadedMoreReports: SignalReport[]
    moreReportCount: number
    moreReports: TodayMoreReports | null
    moreReportsInInbox: number
    moreReportsLoading: boolean
    now: number
    recentObjects: FileSystemEntry[]
    reportId: string | null
    reportPreviews: Record<string, TodayReportPreview>
    reports: SignalReport[]
    reportsBroken: boolean
    reportsFailed: boolean
    returnFocusReportId: string | null
    showPersonalBriefing: boolean
    shownReportIds: string[]
    topReports: TodayReports | null
    topReportsLoading: boolean
    useSampleData: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayLogicActions {
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
    loadPersonalBriefing: () => any // todayBriefingLogic
    loadPersonalBriefingFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // todayBriefingLogic
    loadPersonalBriefingSuccess: (
        personalBriefing: BriefingApi | null,
        payload?: any
    ) => {
        payload?: any
        personalBriefing: BriefingApi | null
    } // todayBriefingLogic
    refreshBriefing: () => any // todayBriefingLogic
    loadHighlights: () => any // todayHighlightsLogic
    askAi: (
        prompt: string,
        source: TodayAskSource,
        report?: SignalReport
    ) => {
        prompt: string
        report: SignalReport | undefined
        source: TodayAskSource
    }
    askAiFinished: () => {
        value: true
    }
    exploreOpened: (
        product: string,
        position: number
    ) => {
        position: number
        product: string
    }
    itemOpened: (item: BriefingItemApi) => {
        item: BriefingItemApi
    }
    loadMoreReports: () => any
    loadMoreReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMoreReportsSuccess: (
        moreReports: TodayMoreReports | null,
        payload?: any
    ) => {
        moreReports: TodayMoreReports | null
        payload?: any
    }
    loadTopReports: () => any
    loadTopReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTopReportsSuccess: (
        topReports: TodayReports,
        payload?: any
    ) => {
        topReports: TodayReports
        payload?: any
    }
    reportOpened: (
        report: SignalReport,
        source: TodayReportOpenSource
    ) => {
        report: SignalReport
        source: TodayReportOpenSource
    }
    retryFailedLoads: () => {
        value: true
    }
    setHomeScrollTop: (top: number | null) => {
        top: number | null
    }
    setListExpanded: (
        list: TodayList,
        expanded: boolean
    ) => {
        expanded: boolean
        list: TodayList
    }
    setReturnFocusReportId: (reportId: string | null) => {
        reportId: string | null
    }
    setUseSampleData: (useSampleData: boolean) => {
        useSampleData: boolean
    }
    showMoreForYou: () => {
        value: true
    }
    tick: () => {
        value: true
    }
    toggleReportRow: (
        rowKey: string,
        reportId: string
    ) => {
        reportId: string
        rowKey: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        reportId: (location: { hash: string; pathname: string; search: string }) => string | null
        reports: (topReports: TodayReports | null) => SignalReport[]
        moreReportCount: (topReports: TodayReports | null) => number
        hour: (now: number) => number
        greeting: (hour: number, user: UserType | null) => string
        recentObjects: (recents: FileSystemEntry[]) => FileSystemEntry[]
        showPersonalBriefing: (personalBriefing: BriefingApi | null, useSampleData: boolean) => boolean
        briefingItems: (
            personalBriefing: BriefingApi | null,
            showPersonalBriefing: boolean,
            reportStateOverrides: Record<string, BriefingItemStateEnumApi>
        ) => BriefingItemApi[]
        shownReportIds: (
            showPersonalBriefing: boolean,
            briefingItems: BriefingItemApi[],
            reports: SignalReport[]
        ) => string[]
        currentMoreReports: (
            moreReports: TodayMoreReports | null,
            shownReportIds: string[],
            useSampleData: boolean
        ) => TodayMoreReports | null
        loadedMoreReports: (currentMoreReports: TodayMoreReports | null) => SignalReport[]
        canLoadMoreReports: (
            currentMoreReports: TodayMoreReports | null,
            useSampleData: boolean,
            showPersonalBriefing: boolean,
            personalBriefing: BriefingApi | null,
            moreReportCount: number
        ) => boolean
        moreReportsInInbox: (currentMoreReports: TodayMoreReports | null) => number
        forYouRows: (
            showPersonalBriefing: boolean,
            briefingItems: BriefingItemApi[],
            reports: SignalReport[],
            loadedMoreReports: SignalReport[],
            forYouHighlights: HighlightItemApi[],
            doneHighlightKeys: string[],
            reportStateOverrides: Record<string, BriefingItemStateEnumApi>
        ) => TodayForYouRows
        reportsBroken: (
            reportsFailed: boolean,
            topReports: TodayReports | null,
            showPersonalBriefing: boolean
        ) => boolean
        forYouReady: (
            showPersonalBriefing: boolean,
            topReports: TodayReports | null,
            reportsFailed: boolean,
            highlightsPending: boolean,
            highlightsWaitOver: boolean,
            forYouRows: TodayForYouRows
        ) => boolean
        forYouFailedNote: (reportsBroken: boolean, highlightsFailed: boolean) => string | null
        forYouOpenCount: (forYouRows: TodayForYouRows) => number
        forYouVisibleRows: (forYouRows: TodayForYouRows, listExpanded: Record<TodayList, boolean>) => TodayForYouRow[]
        forYouCanShowMore: (
            forYouRows: TodayForYouRows,
            listExpanded: Record<TodayList, boolean>,
            canLoadMoreReports: boolean
        ) => boolean
        forYouCanShowLess: (forYouRows: TodayForYouRows, listExpanded: Record<TodayList, boolean>) => boolean
        isNewProject: (currentTeam: TeamPublicType | TeamType | null, useSampleData: boolean) => boolean
        exploreItems: (currentTeam: TeamPublicType | TeamType | null) => TodayExploreItem[]
        reportPreviews: (
            reports: SignalReport[],
            loadedMoreReports: SignalReport[],
            briefingItems: BriefingItemApi[]
        ) => Record<string, TodayReportPreview>
    }
}

export type todayLogicType = MakeLogicType<todayLogicValues, todayLogicActions, Record<string, any>, todayLogicMeta>

export const todayLogic = kea<todayLogicType>([
    path(['scenes', 'project-homepage', 'today', 'todayLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            teamLogic,
            ['currentTeam', 'currentProjectId'],
            recentItemsModel,
            ['recents', 'recentsHasLoaded'],
            todayBriefingLogic,
            ['personalBriefing', 'personalBriefingLoading', 'briefingWaiting'],
            todayHighlightsLogic,
            [
                'highlights',
                'highlightsLoading',
                'highlightsFailed',
                'highlightsPending',
                'highlightsWaitOver',
                'forYouHighlights',
                'doneHighlightKeys',
            ],
            todayVerdictLogic,
            ['reportStateOverrides'],
        ],
        actions: [
            router,
            ['locationChanged'],
            todayBriefingLogic,
            ['loadPersonalBriefing', 'loadPersonalBriefingSuccess', 'loadPersonalBriefingFailure', 'refreshBriefing'],
            todayHighlightsLogic,
            ['loadHighlights'],
        ],
    })),
    actions({
        // `report` is the report the person reads. Without it, the context is the briefing or the report list.
        askAi: (prompt: string, source: TodayAskSource, report?: SignalReport) => ({ prompt, source, report }),
        askAiFinished: true,
        reportOpened: (report: SignalReport, source: TodayReportOpenSource) => ({ report, source }),
        itemOpened: (item: BriefingItemApi) => ({ item }),
        toggleReportRow: (rowKey: string, reportId: string) => ({ rowKey, reportId }),
        exploreOpened: (product: string, position: number) => ({ product, position }),
        setHomeScrollTop: (top: number | null) => ({ top }),
        setReturnFocusReportId: (reportId: string | null) => ({ reportId }),
        setListExpanded: (list: TodayList, expanded: boolean) => ({ list, expanded }),
        showMoreForYou: true,
        retryFailedLoads: true,
        setUseSampleData: (useSampleData: boolean) => ({ useSampleData }),
        tick: true,
    }),
    loaders(({ values }) => ({
        topReports: [
            null as TodayReports | null,
            {
                loadTopReports: async (): Promise<TodayReports> => {
                    if (values.useSampleData) {
                        return sampleTopReports(TOP_REPORT_COUNT)
                    }
                    if (values.currentProjectId === null) {
                        return { results: [], count: 0 }
                    }
                    // The person's own reports, ranked and counted the way the Today briefing ranks them.
                    // A P0 nobody owns ranks above every one of them, so Today leaves it to the Inbox.
                    let response
                    try {
                        response = await signalsReportsForYouRetrieve(String(values.currentProjectId), {
                            limit: TOP_REPORT_COUNT,
                            include_unowned: false,
                        })
                    } catch (error) {
                        if (error instanceof ApiError && error.status === 403) {
                            return { results: [], count: 0 }
                        }
                        throw error
                    }
                    // Today passes reports to the Inbox's helpers, which take the handwritten SignalReport. The
                    // generated row type is wider (string status and priority, read-only arrays), so the cast
                    // goes away when the Inbox moves to generated types.
                    return { results: response.results as unknown as SignalReport[], count: response.count }
                },
            },
        ],
        moreReports: [
            null as TodayMoreReports | null,
            {
                loadMoreReports: async (): Promise<TodayMoreReports | null> => {
                    if (values.currentProjectId === null) {
                        return null
                    }
                    const exclude = values.shownReportIds
                    const loaded = values.loadedMoreReports
                    const response = await signalsReportsForYouRetrieve(String(values.currentProjectId), {
                        limit: MORE_REPORTS_PAGE_SIZE,
                        offset: loaded.length,
                        exclude: exclude.length > 0 ? exclude : undefined,
                        include_unowned: false,
                    })
                    const results = [...loaded, ...(response.results as unknown as SignalReport[])]
                    return {
                        exclude,
                        results,
                        count: response.count,
                        hasMore: response.results.length === MORE_REPORTS_PAGE_SIZE && results.length < response.count,
                    }
                },
            },
        ],
    })),
    reducers({
        // Turned on with `?sample=1` and kept until `?sample=0`, so the sample survives moving between pages.
        useSampleData: [false, { persist: true }, { setUseSampleData: (_, { useSampleData }) => useSampleData }],
        // A question about a report waits for the report's current state before PostHog AI opens.
        askingAi: [false, { askAi: (_, { report }) => !!report, askAiFinished: () => false }],
        expandedReportRows: [
            {} as Record<string, boolean>,
            {
                toggleReportRow: (state, { rowKey }) => {
                    const { [rowKey]: open, ...rest } = state
                    return open ? rest : { ...state, [rowKey]: true }
                },
            },
        ],
        homeScrollTop: [
            null as number | null,
            {
                setHomeScrollTop: (_, { top }) => top,
                locationChanged: (top, { pathname }) => (isTodayPath(pathname) ? top : null),
            },
        ],
        returnFocusReportId: [
            null as string | null,
            {
                setReturnFocusReportId: (_, { reportId }) => reportId,
                locationChanged: (reportId, { pathname }) =>
                    isTodayPath(pathname) ? (reportIdFromPath(pathname) ?? reportId) : null,
            },
        ],
        reportsFailed: [
            false,
            {
                loadTopReports: () => false,
                loadTopReportsFailure: () => true,
            },
        ],
        now: [Date.now(), { tick: () => Date.now() }],
        // A refreshed briefing names other reports, so the list the sidebar loaded past the old one goes.
        moreReports: {
            refreshBriefing: () => null,
            setUseSampleData: () => null,
        },
        topReports: {
            setUseSampleData: () => null,
        },
        listExpanded: [
            { for_you: false, recents: false } as Record<TodayList, boolean>,
            {
                setListExpanded: (state, { list, expanded }) => ({ ...state, [list]: expanded }),
            },
        ],
    }),
    selectors({
        reportId: [
            () => [router.selectors.location],
            (location: { pathname: string }): string | null => reportIdFromPath(location.pathname),
        ],
        reports: [
            (s) => [s.topReports],
            (topReports: TodayReports | null): SignalReport[] => topReports?.results ?? [],
        ],
        moreReportCount: [
            (s) => [s.topReports],
            (topReports: TodayReports | null): number =>
                topReports ? Math.max(topReports.count - topReports.results.length, 0) : 0,
        ],
        hour: [(s) => [s.now], (now: number): number => new Date(now).getHours()],
        greeting: [
            (s) => [s.hour, s.user],
            (hour: number, user: UserType | null): string => greetingForHour(hour, user?.first_name),
        ],
        recentObjects: [
            (s) => [s.recents],
            (recents: FileSystemEntry[]): FileSystemEntry[] => recentObjectsForHome(recents, RECENT_OBJECT_MORE_COUNT),
        ],
        showPersonalBriefing: [
            (s) => [s.personalBriefing, s.useSampleData],
            (personalBriefing: BriefingApi | null, useSampleData: boolean): boolean =>
                !useSampleData && hasBriefingText(personalBriefing),
        ],
        briefingItems: [
            (s) => [s.personalBriefing, s.showPersonalBriefing, s.reportStateOverrides],
            (
                personalBriefing: BriefingApi | null,
                showPersonalBriefing: boolean,
                reportStateOverrides: Record<string, BriefingItemStateEnumApi>
            ): BriefingItemApi[] => {
                if (!showPersonalBriefing || !personalBriefing) {
                    return []
                }
                return personalBriefing.items.map((item) => {
                    const reportId = itemReportId(item)
                    const state = reportId ? reportStateOverrides[reportId] : undefined
                    return state ? { ...item, state } : item
                })
            },
        ],
        shownReportIds: [
            (s) => [s.showPersonalBriefing, s.briefingItems, s.reports],
            (showPersonalBriefing: boolean, briefingItems: BriefingItemApi[], reports: SignalReport[]): string[] =>
                showPersonalBriefing
                    ? briefingItems.map(itemReportId).filter((id): id is string => id !== null)
                    : reports.map((report) => report.id),
        ],
        currentMoreReports: [
            (s) => [s.moreReports, s.shownReportIds, s.useSampleData],
            (
                moreReports: TodayMoreReports | null,
                shownReportIds: string[],
                useSampleData: boolean
            ): TodayMoreReports | null =>
                moreReports && !useSampleData && objectsEqual(moreReports.exclude, shownReportIds) ? moreReports : null,
        ],
        loadedMoreReports: [
            (s) => [s.currentMoreReports],
            (currentMoreReports: TodayMoreReports | null): SignalReport[] => currentMoreReports?.results ?? [],
        ],
        canLoadMoreReports: [
            (s) => [
                s.currentMoreReports,
                s.useSampleData,
                s.showPersonalBriefing,
                s.personalBriefing,
                s.moreReportCount,
            ],
            (
                currentMoreReports: TodayMoreReports | null,
                useSampleData: boolean,
                showPersonalBriefing: boolean,
                personalBriefing: BriefingApi | null,
                moreReportCount: number
            ): boolean => {
                if (useSampleData) {
                    return false
                }
                if (currentMoreReports) {
                    return currentMoreReports.hasMore
                }
                return showPersonalBriefing ? (personalBriefing?.more_reports_count ?? 0) > 0 : moreReportCount > 0
            },
        ],
        moreReportsInInbox: [
            (s) => [s.currentMoreReports],
            (currentMoreReports: TodayMoreReports | null): number =>
                currentMoreReports && !currentMoreReports.hasMore
                    ? Math.max(currentMoreReports.count - currentMoreReports.results.length, 0)
                    : 0,
        ],
        forYouRows: [
            (s) => [
                s.showPersonalBriefing,
                s.briefingItems,
                s.reports,
                s.loadedMoreReports,
                s.forYouHighlights,
                s.doneHighlightKeys,
                s.reportStateOverrides,
            ],
            (
                showPersonalBriefing: boolean,
                briefingItems: BriefingItemApi[],
                reports: SignalReport[],
                loadedMoreReports: SignalReport[],
                highlights: HighlightItemApi[],
                doneHighlightKeys: string[],
                reportStateOverrides: Record<string, BriefingItemStateEnumApi>
            ): TodayForYouRows =>
                forYouRows({
                    showPersonalBriefing,
                    briefingItems,
                    reports,
                    loadedMoreReports,
                    highlights,
                    doneHighlightKeys,
                    reportStateOverrides,
                }),
        ],
        reportsBroken: [
            (s) => [s.reportsFailed, s.topReports, s.showPersonalBriefing],
            (reportsFailed: boolean, topReports: TodayReports | null, showPersonalBriefing: boolean): boolean =>
                reportsFailed && topReports === null && !showPersonalBriefing,
        ],
        forYouReady: [
            (s) => [
                s.showPersonalBriefing,
                s.topReports,
                s.reportsFailed,
                s.highlightsPending,
                s.highlightsWaitOver,
                s.forYouRows,
            ],
            (
                showPersonalBriefing: boolean,
                topReports: TodayReports | null,
                reportsFailed: boolean,
                highlightsPending: boolean,
                highlightsWaitOver: boolean,
                { rows }: TodayForYouRows
            ): boolean =>
                (showPersonalBriefing || topReports !== null || reportsFailed) &&
                (!highlightsPending || (highlightsWaitOver && rows.length > 0)),
        ],
        forYouFailedNote: [
            (s) => [s.reportsBroken, s.highlightsFailed],
            (reportsBroken: boolean, highlightsFailed: boolean): string | null =>
                reportsBroken && highlightsFailed
                    ? 'Reports and highlights didn’t load.'
                    : reportsBroken
                      ? 'Reports didn’t load.'
                      : highlightsFailed
                        ? 'Highlights didn’t load.'
                        : null,
        ],
        forYouOpenCount: [
            (s) => [s.forYouRows],
            ({ rows }: TodayForYouRows): number => rows.filter((row) => !row.done).length,
        ],
        forYouVisibleRows: [
            (s) => [s.forYouRows, s.listExpanded],
            ({ rows, limit }: TodayForYouRows, listExpanded: Record<TodayList, boolean>): TodayForYouRow[] =>
                listExpanded.for_you ? rows : rows.slice(0, limit),
        ],
        forYouCanShowMore: [
            (s) => [s.forYouRows, s.listExpanded, s.canLoadMoreReports],
            (
                { rows, limit }: TodayForYouRows,
                listExpanded: Record<TodayList, boolean>,
                canLoadMoreReports: boolean
            ): boolean => (!listExpanded.for_you && rows.length > limit) || canLoadMoreReports,
        ],
        forYouCanShowLess: [
            (s) => [s.forYouRows, s.listExpanded],
            ({ rows }: TodayForYouRows, listExpanded: Record<TodayList, boolean>): boolean =>
                listExpanded.for_you && rows.length > VISIBLE_ROWS + 1,
        ],
        isNewProject: [
            (s) => [s.currentTeam, s.useSampleData],
            (currentTeam: TeamPublicType | TeamType | null, useSampleData: boolean): boolean =>
                !useSampleData && currentTeam?.ingested_event === false,
        ],
        exploreItems: [
            (s) => [s.currentTeam],
            (): TodayExploreItem[] => EXPLORE_ITEMS.filter((item) => !getProductAccessDisabledReason(item)),
        ],
        reportPreviews: [
            (s) => [s.reports, s.loadedMoreReports, s.briefingItems],
            (
                reports: SignalReport[],
                loadedMoreReports: SignalReport[],
                briefingItems: BriefingItemApi[]
            ): Record<string, TodayReportPreview> => {
                const previews: Record<string, TodayReportPreview> = {}
                for (const report of [...reports, ...loadedMoreReports]) {
                    const preview = reportPreview(report)
                    if (preview) {
                        previews[report.id] = preview
                    }
                }
                for (const item of briefingItems) {
                    const preview = briefingItemPreview(item)
                    if (preview) {
                        previews[item.key] = preview
                    }
                }
                return previews
            },
        ],
    }),
    listeners(({ actions, values, cache }) => {
        // The ranking dataset reads these as the home's exposure log: one impression per report per mount,
        // like the Inbox list.
        const impress = (list: TodayReportList, ranked: TodayRankedReport[], listSize: number): void => {
            const impressed: Set<string> = (cache.impressedReportIds ??= new Set<string>())
            const fresh = ranked.filter(({ report }) => !impressed.has(report.reportId))
            if (fresh.length === 0) {
                return
            }
            fresh.forEach(({ report }) => impressed.add(report.reportId))
            captureTodayReportsImpressed({
                list,
                reports: fresh.map(({ report }) => report),
                ranks: fresh.map(({ rank }) => rank),
                listSize,
            })
        }
        const captureImpressions = (): void => {
            if (values.useSampleData) {
                return
            }
            const { rows } = values.forYouRows
            if (values.showPersonalBriefing) {
                const ranked = briefingRows(rows).flatMap((row, index) =>
                    row.reportId ? [{ report: briefingItemSnapshot(row.item, row.reportId), rank: index + 1 }] : []
                )
                impress('briefing', ranked, values.briefingItems.length)
            } else if (!values.personalBriefingLoading) {
                // The team list only stands in for the briefing, so it counts once the briefing is known to be absent.
                impress(
                    'briefing',
                    reportRows(rows, 'list').map((row, index) => ({
                        report: signalReportSnapshot(row.report),
                        rank: index + 1,
                    })),
                    values.reports.length
                )
            }
            const moreRows = reportRows(rows, 'more')
            impress(
                'sidebar_more',
                moreRows.map((row, index) => ({ report: signalReportSnapshot(row.report), rank: index + 1 })),
                moreRows.length
            )
        }
        return {
            askAi: async ({ prompt, source, report }, breakpoint) => {
                let context: TodayAskContext
                // Sample reports have ids that do not exist, so PostHog AI gets no context to look up. A real
                // report can still open while sample mode is on, so a report decides by its own id.
                if (report) {
                    context = isSampleReportId(report.id)
                        ? { kind: 'none' }
                        : { kind: 'report', ...(await currentReportContext(report, values.currentProjectId)) }
                    breakpoint()
                } else {
                    context = values.useSampleData
                        ? { kind: 'none' }
                        : values.showPersonalBriefing && values.personalBriefing
                          ? { kind: 'briefing', briefing: values.personalBriefing }
                          : { kind: 'reports', reports: values.reports }
                }
                actions.askAiFinished()
                router.actions.push(urls.ai(undefined, todayAskPrompt(prompt, context)))
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today ai asked', {
                    source,
                    context: context.kind,
                    briefing_id: context.kind === 'briefing' ? context.briefing.id : null,
                    report_id: context.kind === 'report' ? context.report.id : null,
                })
            },
            tick: () => {
                const { now, highlights, personalBriefing } = values
                if (highlights && !values.highlightsLoading && now >= Date.parse(highlights.refresh_at)) {
                    actions.loadHighlights()
                }
                if (
                    personalBriefing &&
                    !values.useSampleData &&
                    !values.personalBriefingLoading &&
                    !values.briefingWaiting &&
                    now >= Date.parse(personalBriefing.refresh_at)
                ) {
                    actions.loadPersonalBriefing()
                }
            },
            setUseSampleData: ({ useSampleData }) => {
                actions.loadTopReports()
                if (!useSampleData) {
                    actions.loadPersonalBriefing()
                }
            },
            loadPersonalBriefingSuccess: () => {
                captureImpressions()
            },
            loadPersonalBriefingFailure: () => {
                captureImpressions()
            },
            itemOpened: ({ item }) => {
                const reportId = itemReportId(item)
                const rank = briefingRows(values.forYouRows.rows).findIndex((row) => row.key === item.key) + 1
                if (reportId) {
                    captureTodayReportOpened({
                        report: briefingItemSnapshot(item, reportId),
                        list: 'briefing',
                        rank: rank || null,
                        listSize: values.briefingItems.length,
                        source: 'list',
                    })
                }
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today item opened', {
                    group: item.group,
                    source: item.source,
                    reason: item.reason,
                    rank: rank || null,
                    state: item.state,
                    surface: 'list',
                })
            },
            exploreOpened: ({ product, position }) => {
                posthog.capture('today explore opened', { product, position })
            },
            toggleReportRow: ({ rowKey, reportId }) => {
                if (!values.expandedReportRows[rowKey] || values.useSampleData) {
                    return
                }
                const { rows } = values.forYouRows
                const briefing = briefingRows(rows)
                const briefingIndex = briefing.findIndex((row) => row.reportId === reportId)
                if (briefingIndex !== -1) {
                    const { item } = briefing[briefingIndex]
                    // pinned: analytics event name and properties. Renaming them breaks dashboards.
                    posthog.capture('today report previewed', {
                        list: 'personal',
                        report_id: reportId,
                        source: item.source,
                        reason: item.reason,
                        rank: briefingIndex + 1,
                        state: item.state,
                        has_metric: !!item.report?.metrics.length,
                        surface: 'list',
                    })
                    return
                }
                for (const [list, source] of [
                    ['team', 'list'],
                    ['more', 'more'],
                ] as const) {
                    const listRows = reportRows(rows, source)
                    const index = listRows.findIndex((row) => row.report.id === reportId)
                    if (index !== -1) {
                        posthog.capture('today report previewed', {
                            list,
                            report_id: reportId,
                            rank: index + 1,
                            has_metric: !!listRows[index].report.metrics?.length,
                            surface: 'list',
                        })
                        return
                    }
                }
            },
            showMoreForYou: () => {
                actions.setListExpanded('for_you', true)
                if (values.canLoadMoreReports) {
                    actions.loadMoreReports()
                }
            },
            retryFailedLoads: () => {
                if (values.reportsBroken) {
                    actions.loadTopReports()
                }
                if (values.highlightsFailed) {
                    actions.loadHighlights()
                }
            },
            locationChanged: ({ searchParams }) => {
                const useSampleData = parseSampleParam(searchParams.sample)
                if (useSampleData !== null && useSampleData !== values.useSampleData) {
                    actions.setUseSampleData(useSampleData)
                }
                const { reportId, listExpanded } = values
                if (reportId && !listExpanded.for_you) {
                    const { rows, limit } = values.forYouRows
                    if (rows.findIndex((row) => rowReportId(row) === reportId) >= limit) {
                        actions.setListExpanded('for_you', true)
                    }
                }
            },
            loadTopReportsSuccess: ({ topReports }) => {
                if (values.useSampleData) {
                    return
                }
                captureImpressions()
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today home loaded', {
                    report_count: topReports.results.length,
                    more_report_count: values.moreReportCount,
                })
            },
            loadMoreReports: () => {
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today more reports clicked', { shown_report_count: values.shownReportIds.length })
            },
            loadMoreReportsSuccess: () => {
                captureImpressions()
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today more reports loaded', {
                    report_count: values.loadedMoreReports.length,
                    inbox_report_count: values.moreReportsInInbox,
                })
            },
            loadMoreReportsFailure: () => {
                lemonToast.error('Couldn’t load more reports. Try again in a minute.')
            },
            reportOpened: ({ report, source }) => {
                if (values.useSampleData) {
                    return
                }
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today report opened', {
                    report_id: report.id,
                    priority: report.priority ?? null,
                    has_pr: !!report.implementation_pr_url,
                    source,
                })
                const listRows = reportRows(values.forYouRows.rows, source)
                const rank = listRows.findIndex((row) => row.report.id === report.id) + 1
                captureTodayReportOpened({
                    report: signalReportSnapshot(report),
                    list: source === 'more' ? 'sidebar_more' : 'briefing',
                    rank: rank || null,
                    listSize: listRows.length,
                    source,
                })
            },
        }
    }),
    afterMount(({ actions, values, cache }) => {
        // `now` defaults to the time the module loaded, so set it before anything reads the hour.
        actions.tick()
        const useSampleData = parseSampleParam(router.values.searchParams.sample)
        if (useSampleData !== null && useSampleData !== values.useSampleData) {
            actions.setUseSampleData(useSampleData)
        } else {
            actions.loadTopReports()
            if (!values.useSampleData) {
                actions.loadPersonalBriefing()
            }
        }
        cache.disposables.add(() => {
            const clock = window.setInterval(() => actions.tick(), CLOCK_MS)
            return () => clearInterval(clock)
        }, 'clock')
    }),
])
