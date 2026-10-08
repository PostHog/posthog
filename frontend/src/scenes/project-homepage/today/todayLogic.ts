import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import type { LocationChangedPayload } from 'kea-router/lib/types'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { navigateToHref } from 'lib/utils/navigateToHref'
import { getLocalTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { TodayReportCard, TodayReportPreview } from '~/layout/today/todayPreviewCards'
import { TeamType, UserType } from '~/types'

import {
    signalsReportsForYouRetrieve,
    signalsReportsRetrieve,
    signalsReportsReviewersMeDestroy,
    signalsReportsStateCreate,
} from 'products/signals/frontend/generated/api'
import type {
    SignalReportStateEnumApi,
    SignalReportStateRequestApi,
} from 'products/signals/frontend/generated/api.schemas'
import { openDismissReportDialog } from 'products/signals/frontend/inbox/components/shell/DismissReportDialog'
import { openResolveReportDialog } from 'products/signals/frontend/inbox/components/shell/ResolveReportDialog'
import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { suppressDismissalPayload } from 'products/signals/frontend/inbox/utils/dismissalReasons'
import { todayBriefingRefreshCreate, todayBriefingRetrieve } from 'products/today/frontend/generated/api'
import type {
    BriefingApi,
    BriefingItemApi,
    BriefingItemStateEnumApi,
} from 'products/today/frontend/generated/api.schemas'

import type { TeamPublicType } from '../../../types'
import { TodayAskContext, todayAskPrompt } from './todayAskPrompt'
import {
    TodayItemOpenSurface,
    briefingDayKey,
    briefingItemReportCard,
    hasBriefingText,
    isBriefingSettled,
    isExternalHref,
    itemHref,
    itemNamesPerson,
    itemReportId,
} from './todayBriefingItems'
import { SAMPLE_BRIEFING, isSampleReportId, parseSampleParam, sampleTopReports } from './todaySampleReports'
import { TodayBriefingSegment, briefingForReports, teamReportCard } from './todaySignalReports'

export const TOP_REPORT_COUNT = 5
// The most reports the for_you endpoint returns in one call (MAX_FOR_YOU_REPORTS on the backend).
export const MORE_REPORTS_LIMIT = 20
const CLOCK_MS = 30_000
export const BRIEFING_POLL_MS = 5_000
// The run's budget is 10 minutes (RUN_TIMEOUT in logic/generate.py). Stop asking a little after that.
const MAX_BRIEFING_POLLS = 132

/** Where a report was opened from, sent with the `today report opened` event. */
export type TodayReportOpenSource = 'briefing' | 'chip' | 'sidebar' | 'sidebar_more'

/** Where a question to PostHog AI came from, sent with the `today ai asked` event. */
export type TodayAskSource = 'ask_box' | 'walk_through' | 'report_page'

/** What a person decides about a report from Today. */
export type TodayReportVerdict = 'resolve' | 'dismiss'

/** Where the person gave the verdict, sent with the `today report state changed` event. */
export type TodayReportVerdictSurface = TodayReportPreview['surface'] | 'report_page'

/** The report a verdict acts on. */
export interface TodayReportVerdictTarget {
    reportId: string
    title: string
    /** The backend closes an open implementation pull request on either verdict, so the person confirms first. */
    hasOpenPullRequest: boolean
}

interface TodayReportVerdictCopy {
    apiState: SignalReportStateEnumApi
    itemState: BriefingItemStateEnumApi
    success: string
    successClosingPullRequest: string
    failure: string
    confirmTitle: string
    confirmLabel: string
    reasonTitle: string
    reasonDescription: string
}

const VERDICTS: Record<TodayReportVerdict, TodayReportVerdictCopy> = {
    resolve: {
        apiState: 'resolved',
        itemState: 'done',
        success: 'Report resolved',
        successClosingPullRequest: 'Report resolved. Its pull request is closing.',
        failure: 'Couldn’t resolve the report. Try again, or resolve it from the Inbox.',
        confirmTitle: 'Resolve this report?',
        confirmLabel: 'Resolve and close PR',
        reasonTitle: 'Why did you resolve this report?',
        reasonDescription: 'The reason is saved on the report.',
    },
    dismiss: {
        apiState: 'suppressed',
        itemState: 'dismissed',
        success: 'Report dismissed',
        successClosingPullRequest: 'Report dismissed. Its pull request is closing.',
        failure: 'Couldn’t dismiss the report. Try again, or dismiss it from the Inbox.',
        confirmTitle: 'Dismiss this report?',
        confirmLabel: 'Dismiss and close PR',
        reasonTitle: 'Why did you dismiss this report?',
        reasonDescription:
            'The reason is saved on the report. The agent that filed it reads your note on its next run.',
    },
}

/** The count behind the Inbox link: reports for the person beyond the shown ones, or open in the project. */
export interface TodayInboxMore {
    count: number
    scope: 'for_you' | 'project'
}

export interface TodayReports {
    results: SignalReport[]
    /** Every report that matches the filter, including the ones past the top five. */
    count: number
}

const COUNT_WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']

/** The report a Today report page shows, read from a path such as `/project/1/home/reports/abc`. */
export function reportIdFromPath(pathname: string): string | null {
    const match = removeProjectIdIfPresent(pathname).match(/^\/home\/reports\/([^/]+)\/?$/)
    return match ? decodeURIComponent(match[1]) : null
}

export function countWord(count: number): string {
    return COUNT_WORDS[count] ?? String(count)
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

export function reportSummaryForHour(hour: number, count: number): string {
    if (count === 0) {
        return 'Nothing needs your attention'
    }
    const reports = `${countWord(count)} ${count === 1 ? 'report' : 'reports'}`
    const verb = count === 1 ? 'needs' : 'need'
    if (hour < 5) {
        return `${reports} ${count === 1 ? 'is' : 'are'} ready for tomorrow`
    }
    if (hour < 12) {
        return `${reports} ${verb} your attention this morning`
    }
    if (hour < 17) {
        return `${reports} ${verb} your attention this afternoon`
    }
    return `${reports} still ${verb} your attention`
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

/** How many of the briefing's items were resolved or dismissed since it was written. */
export interface TodayBriefingProgress {
    done: number
    total: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayLogicValues {
    currentProjectId: number | string // teamLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    user: UserType | null // userLogic
    askingAi: boolean
    briefing: TodayBriefingSegment[][]
    briefingItems: BriefingItemApi[]
    briefingPolls: number
    briefingProgress: TodayBriefingProgress | null
    briefingWaiting: boolean
    canLoadMoreReports: boolean
    gaveUpWaitingFor: string | null
    greeting: string
    hour: number
    hoveredItemKey: string | null
    hoveredReportId: string | null
    inboxMore: TodayInboxMore | null
    moreReportCount: number
    moreReportPreviews: Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>>
    moreReports: TodayReports | null
    moreReportsInInbox: number
    moreReportsLoading: boolean
    now: number
    personalBriefing: BriefingApi | null
    personalBriefingFailed: boolean
    personalBriefingLoading: boolean
    refreshedBriefing: BriefingApi | null
    refreshedBriefingLoading: boolean
    reloadingAfterRefresh: boolean
    reportId: string | null
    reportPreviews: Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>>
    reportStateOverrides: Record<string, BriefingItemStateEnumApi>
    reportSummary: string
    reports: SignalReport[]
    reportsFailed: boolean
    showPersonalBriefing: boolean
    shownReportIds: string[]
    sidebarMoreReports: SignalReport[]
    teamReportPreviews: Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>>
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
    addReportVerdictReason: (
        target: TodayReportVerdictTarget,
        verdict: TodayReportVerdict
    ) => {
        target: TodayReportVerdictTarget
        verdict: TodayReportVerdict
    }
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
    itemOpened: (
        item: BriefingItemApi,
        surface: TodayItemOpenSurface
    ) => {
        item: BriefingItemApi
        surface: TodayItemOpenSurface
    }
    leaveReportReview: (
        reportId: string,
        surface: TodayReportVerdictSurface
    ) => {
        reportId: string
        surface: TodayReportVerdictSurface
    }
    leaveReportReviewFailure: (reportId: string) => {
        reportId: string
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
        moreReports: TodayReports,
        payload?: any
    ) => {
        moreReports: TodayReports
        payload?: any
    }
    loadPersonalBriefing: () => any
    loadPersonalBriefingFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPersonalBriefingSuccess: (
        personalBriefing: BriefingApi | null,
        payload?: any
    ) => {
        personalBriefing: BriefingApi | null
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
    openItem: (
        item: BriefingItemApi,
        surface: TodayItemOpenSurface
    ) => {
        item: BriefingItemApi
        surface: TodayItemOpenSurface
    }
    openReport: (
        report: SignalReport,
        source: TodayReportOpenSource
    ) => {
        report: SignalReport
        source: TodayReportOpenSource
    }
    pollBriefing: () => {
        value: true
    }
    refreshBriefing: () => any
    refreshBriefingFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    refreshBriefingSuccess: (
        refreshedBriefing: BriefingApi | null,
        payload?: any
    ) => {
        refreshedBriefing: BriefingApi | null
        payload?: any
    }
    reportOpened: (
        report: SignalReport,
        source: TodayReportOpenSource
    ) => {
        report: SignalReport
        source: TodayReportOpenSource
    }
    reportPreviewed: (
        cardKey: string,
        surface: TodayReportPreview['surface']
    ) => {
        cardKey: string
        surface: 'briefing' | 'sidebar'
    }
    requestReportVerdict: (
        target: TodayReportVerdictTarget,
        verdict: TodayReportVerdict,
        surface: TodayReportVerdictSurface
    ) => {
        surface: TodayReportVerdictSurface
        target: TodayReportVerdictTarget
        verdict: TodayReportVerdict
    }
    setHoveredItemKey: (itemKey: string | null) => {
        itemKey: string | null
    }
    setHoveredReportId: (reportId: string | null) => {
        reportId: string | null
    }
    setReportVerdict: (
        target: TodayReportVerdictTarget,
        verdict: TodayReportVerdict,
        surface: TodayReportVerdictSurface
    ) => {
        surface: TodayReportVerdictSurface
        target: TodayReportVerdictTarget
        verdict: TodayReportVerdict
    }
    setReportVerdictFailure: (reportId: string) => {
        reportId: string
    }
    setUseSampleData: (useSampleData: boolean) => {
        useSampleData: boolean
    }
    stopWaitingForBriefing: (briefingId: string) => {
        briefingId: string
    }
    tick: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        reportId: (location: { hash: string; pathname: string; search: string }) => string | null
        reports: (topReports: TodayReports | null) => SignalReport[]
        moreReportCount: (topReports: TodayReports | null) => number
        briefing: (reports: SignalReport[], useSampleData: boolean) => TodayBriefingSegment[][]
        hour: (now: number) => number
        greeting: (hour: number, user: UserType | null) => string
        reportSummary: (hour: number, reports: SignalReport[]) => string
        showPersonalBriefing: (personalBriefing: BriefingApi | null, useSampleData: boolean) => boolean
        inboxMore: (personalBriefing: BriefingApi | null) => TodayInboxMore | null
        briefingItems: (
            personalBriefing: BriefingApi | null,
            showPersonalBriefing: boolean,
            reportStateOverrides: Record<string, BriefingItemStateEnumApi>
        ) => BriefingItemApi[]
        reportPreviews: (
            briefingItems: BriefingItemApi[]
        ) => Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>>
        teamReportPreviews: (
            reports: SignalReport[]
        ) => Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>>
        briefingProgress: (briefingItems: BriefingItemApi[]) => TodayBriefingProgress | null
        shownReportIds: (
            showPersonalBriefing: boolean,
            briefingItems: BriefingItemApi[],
            reports: SignalReport[]
        ) => string[]
        sidebarMoreReports: (
            moreReports: TodayReports | null,
            shownReportIds: string[],
            useSampleData: boolean
        ) => SignalReport[]
        moreReportPreviews: (
            sidebarMoreReports: SignalReport[]
        ) => Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>>
        canLoadMoreReports: (
            moreReports: TodayReports | null,
            useSampleData: boolean,
            showPersonalBriefing: boolean,
            personalBriefing: BriefingApi | null,
            moreReportCount: number
        ) => boolean
        moreReportsInInbox: (
            moreReports: TodayReports | null,
            showPersonalBriefing: boolean,
            briefingItems: BriefingItemApi[],
            reports: SignalReport[]
        ) => number
        briefingWaiting: (
            personalBriefing: BriefingApi | null,
            gaveUpWaitingFor: string | null,
            refreshedBriefingLoading: boolean,
            reloadingAfterRefresh: boolean
        ) => boolean
    }
}

export type todayLogicType = MakeLogicType<todayLogicValues, todayLogicActions, Record<string, any>, todayLogicMeta>

/** The same cards keyed for both surfaces. Each card is built once and shared by both. */
function previewsBySurface(
    cards: [string, TodayReportCard][]
): Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>> {
    const previews = (surface: TodayReportPreview['surface']): Record<string, TodayReportPreview> =>
        Object.fromEntries(cards.map(([key, card]) => [key, { kind: 'report', card, surface }]))
    return { briefing: previews('briefing'), sidebar: previews('sidebar') }
}

export const todayLogic = kea<todayLogicType>([
    path(['scenes', 'project-homepage', 'today', 'todayLogic']),
    connect(() => ({
        values: [userLogic, ['user'], teamLogic, ['currentTeam', 'currentProjectId']],
        actions: [router, ['locationChanged']],
    })),
    actions({
        // `report` is the report the person reads. Without it, the context is the briefing or the report list.
        askAi: (prompt: string, source: TodayAskSource, report?: SignalReport) => ({ prompt, source, report }),
        askAiFinished: true,
        setHoveredReportId: (reportId: string | null) => ({ reportId }),
        openReport: (report: SignalReport, source: TodayReportOpenSource) => ({ report, source }),
        reportOpened: (report: SignalReport, source: TodayReportOpenSource) => ({ report, source }),
        setUseSampleData: (useSampleData: boolean) => ({ useSampleData }),
        tick: true,
        setHoveredItemKey: (itemKey: string | null) => ({ itemKey }),
        openItem: (item: BriefingItemApi, surface: TodayItemOpenSurface) => ({ item, surface }),
        itemOpened: (item: BriefingItemApi, surface: TodayItemOpenSurface) => ({ item, surface }),
        reportPreviewed: (cardKey: string, surface: TodayReportPreview['surface']) => ({ cardKey, surface }),
        pollBriefing: true,
        stopWaitingForBriefing: (briefingId: string) => ({ briefingId }),
        requestReportVerdict: (
            target: TodayReportVerdictTarget,
            verdict: TodayReportVerdict,
            surface: TodayReportVerdictSurface
        ) => ({ target, verdict, surface }),
        setReportVerdict: (
            target: TodayReportVerdictTarget,
            verdict: TodayReportVerdict,
            surface: TodayReportVerdictSurface
        ) => ({ target, verdict, surface }),
        setReportVerdictFailure: (reportId: string) => ({ reportId }),
        leaveReportReview: (reportId: string, surface: TodayReportVerdictSurface) => ({ reportId, surface }),
        leaveReportReviewFailure: (reportId: string) => ({ reportId }),
        addReportVerdictReason: (target: TodayReportVerdictTarget, verdict: TodayReportVerdict) => ({
            target,
            verdict,
        }),
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
                    const response = await signalsReportsForYouRetrieve(String(values.currentProjectId), {
                        limit: TOP_REPORT_COUNT,
                        include_unowned: false,
                    })
                    // Today passes reports to the Inbox's helpers, which take the handwritten SignalReport. The
                    // generated row type is wider (string status and priority, read-only arrays), so the cast
                    // goes away when the Inbox moves to generated types.
                    return { results: response.results as unknown as SignalReport[], count: response.count }
                },
            },
        ],
        // Every report the endpoint ranks for the person. The sidebar drops the ones it already shows.
        moreReports: [
            null as TodayReports | null,
            {
                loadMoreReports: async (): Promise<TodayReports> => {
                    if (values.currentProjectId === null) {
                        return { results: [], count: 0 }
                    }
                    const response = await signalsReportsForYouRetrieve(String(values.currentProjectId), {
                        limit: MORE_REPORTS_LIMIT,
                        include_unowned: false,
                    })
                    return { results: response.results as unknown as SignalReport[], count: response.count }
                },
            },
        ],
        personalBriefing: [
            null as BriefingApi | null,
            {
                loadPersonalBriefing: async (): Promise<BriefingApi | null> => {
                    if (values.currentProjectId === null) {
                        return null
                    }
                    return await todayBriefingRetrieve(String(values.currentProjectId), {
                        timezone: getLocalTimeZone(),
                    })
                },
            },
        ],
        refreshedBriefing: [
            null as BriefingApi | null,
            {
                refreshBriefing: async (): Promise<BriefingApi | null> => {
                    if (values.currentProjectId === null) {
                        return null
                    }
                    return await todayBriefingRefreshCreate(String(values.currentProjectId), {
                        timezone: getLocalTimeZone(),
                    })
                },
            },
        ],
    })),
    reducers({
        // Turned on with `?sample=1` and kept until `?sample=0`, so the sample survives moving between pages.
        useSampleData: [false, { persist: true }, { setUseSampleData: (_, { useSampleData }) => useSampleData }],
        // A question about a report waits for the report's current state before PostHog AI opens.
        askingAi: [false, { askAi: (_, { report }) => !!report, askAiFinished: () => false }],
        hoveredReportId: [
            null as string | null,
            {
                setHoveredReportId: (_, { reportId }) => reportId,
                locationChanged: () => null,
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
        hoveredItemKey: [
            null as string | null,
            {
                setHoveredItemKey: (_, { itemKey }) => itemKey,
                locationChanged: () => null,
            },
        ],
        personalBriefingFailed: [
            false,
            {
                loadPersonalBriefingSuccess: () => false,
                loadPersonalBriefingFailure: () => true,
            },
        ],
        // The briefing the page stopped waiting for after the poll budget ran out, so a later one still polls.
        gaveUpWaitingFor: [
            null as string | null,
            {
                stopWaitingForBriefing: (_, { briefingId }) => briefingId,
                refreshBriefingSuccess: () => null,
            },
        ],
        // Polls spent on the briefing in progress. A settled briefing closes the count, so the next
        // one starts with the whole budget.
        briefingPolls: [
            0,
            {
                pollBriefing: (count) => count + 1,
                loadPersonalBriefingSuccess: (count, { personalBriefing }) =>
                    personalBriefing && isBriefingSettled(personalBriefing) ? 0 : count,
                refreshBriefingSuccess: () => 0,
                stopWaitingForBriefing: () => 0,
            },
        ],
        // A refreshed briefing names other reports, so the list the sidebar loaded past the old one goes.
        moreReports: {
            refreshBriefing: () => null,
            setUseSampleData: () => null,
        },
        // The refresh call returns before the page reloads the briefing. Until that reload returns
        // the `writing` briefing, the page still waits, so the badge does not flip back to the button.
        // A verdict shows at once in the text, the left bar and the hover card. The next briefing load
        // gives the same state from the server, and a failed request takes the verdict back.
        reportStateOverrides: [
            {} as Record<string, BriefingItemStateEnumApi>,
            {
                setReportVerdict: (overrides, { target, verdict }) => ({
                    ...overrides,
                    [target.reportId]: VERDICTS[verdict].itemState,
                }),
                setReportVerdictFailure: (overrides, { reportId }) => {
                    const { [reportId]: _, ...rest } = overrides
                    return rest
                },
                leaveReportReview: (overrides, { reportId }) => ({ ...overrides, [reportId]: 'left' }),
                leaveReportReviewFailure: (overrides, { reportId }) => {
                    const { [reportId]: _, ...rest } = overrides
                    return rest
                },
            },
        ],
        reloadingAfterRefresh: [
            false,
            {
                refreshBriefingSuccess: () => true,
                loadPersonalBriefingSuccess: () => false,
                loadPersonalBriefingFailure: () => false,
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
        briefing: [
            (s) => [s.reports, s.useSampleData],
            (reports: SignalReport[], useSampleData: boolean): TodayBriefingSegment[][] =>
                useSampleData ? SAMPLE_BRIEFING : briefingForReports(reports),
        ],
        hour: [(s) => [s.now], (now: number): number => new Date(now).getHours()],
        greeting: [
            (s) => [s.hour, s.user],
            (hour: number, user: UserType | null): string => greetingForHour(hour, user?.first_name),
        ],
        reportSummary: [
            (s) => [s.hour, s.reports],
            (hour: number, reports: SignalReport[]): string => reportSummaryForHour(hour, reports.length),
        ],
        showPersonalBriefing: [
            (s) => [s.personalBriefing, s.useSampleData],
            (personalBriefing: BriefingApi | null, useSampleData: boolean): boolean =>
                !useSampleData && hasBriefingText(personalBriefing),
        ],
        inboxMore: [
            (s) => [s.personalBriefing],
            (personalBriefing: BriefingApi | null): TodayInboxMore | null => {
                if (!personalBriefing) {
                    return null
                }
                if (personalBriefing.more_reports_count > 0) {
                    return { count: personalBriefing.more_reports_count, scope: 'for_you' }
                }
                return personalBriefing.open_reports_count > 0
                    ? { count: personalBriefing.open_reports_count, scope: 'project' }
                    : null
            },
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
        // The card stores its trigger's payload, so each report keeps one object per surface across renders.
        reportPreviews: [
            (s) => [s.briefingItems],
            (
                briefingItems: BriefingItemApi[]
            ): Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>> =>
                // Only items with report details: other items, and deleted reports, have nothing to show.
                previewsBySurface(
                    briefingItems.filter((item) => item.report).map((item) => [item.key, briefingItemReportCard(item)])
                ),
        ],
        // The team's reports stand in until the personal briefing is written, and get the same card.
        teamReportPreviews: [
            (s) => [s.reports],
            (reports: SignalReport[]): Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>> =>
                previewsBySurface(reports.map((report) => [report.id, teamReportCard(report)])),
        ],
        // Shown once something is off the list: "0 of 5 done" reads as a nag, not progress.
        briefingProgress: [
            (s) => [s.briefingItems],
            (briefingItems: BriefingItemApi[]): TodayBriefingProgress | null => {
                const done = briefingItems.filter((item) => item.state !== 'open').length
                return done > 0 ? { done, total: briefingItems.length } : null
            },
        ],
        shownReportIds: [
            (s) => [s.showPersonalBriefing, s.briefingItems, s.reports],
            (showPersonalBriefing: boolean, briefingItems: BriefingItemApi[], reports: SignalReport[]): string[] =>
                showPersonalBriefing
                    ? briefingItems.map(itemReportId).filter((id): id is string => id !== null)
                    : reports.map((report) => report.id),
        ],
        // Read against the list on screen now, so a briefing that loads later does not show a report twice.
        sidebarMoreReports: [
            (s) => [s.moreReports, s.shownReportIds, s.useSampleData],
            (moreReports: TodayReports | null, shownReportIds: string[], useSampleData: boolean): SignalReport[] => {
                if (!moreReports || useSampleData) {
                    return []
                }
                const shown = new Set(shownReportIds)
                return moreReports.results.filter((report) => !shown.has(report.id))
            },
        ],
        moreReportPreviews: [
            (s) => [s.sidebarMoreReports],
            (
                sidebarMoreReports: SignalReport[]
            ): Record<TodayReportPreview['surface'], Record<string, TodayReportPreview>> =>
                previewsBySurface(sidebarMoreReports.map((report) => [report.id, teamReportCard(report)])),
        ],
        // The endpoint has no next page, so the sidebar loads more one time and then links to the Inbox.
        canLoadMoreReports: [
            (s) => [s.moreReports, s.useSampleData, s.showPersonalBriefing, s.personalBriefing, s.moreReportCount],
            (
                moreReports: TodayReports | null,
                useSampleData: boolean,
                showPersonalBriefing: boolean,
                personalBriefing: BriefingApi | null,
                moreReportCount: number
            ): boolean => {
                if (moreReports || useSampleData) {
                    return false
                }
                return showPersonalBriefing ? (personalBriefing?.more_reports_count ?? 0) > 0 : moreReportCount > 0
            },
        ],
        // The endpoint counts the loaded reports plus the other open reports that name the person.
        // What is neither loaded nor already on screen: the count covers the whole set for the person,
        // including briefing items the page ranked past the loaded ones.
        moreReportsInInbox: [
            (s) => [s.moreReports, s.showPersonalBriefing, s.briefingItems, s.reports],
            (
                moreReports: TodayReports | null,
                showPersonalBriefing: boolean,
                briefingItems: BriefingItemApi[],
                reports: SignalReport[]
            ): number => {
                if (!moreReports) {
                    return 0
                }
                // Past the loaded page the count holds only open reports that name the person, so a resolved
                // item, or one the person only claimed, is not in it and must not be taken off it.
                const countedShownIds = showPersonalBriefing
                    ? briefingItems
                          .filter((item) => item.state === 'open' && itemNamesPerson(item))
                          .map(itemReportId)
                          .filter((id): id is string => id !== null)
                    : reports.map((report) => report.id)
                const visible = new Set([...moreReports.results.map((report) => report.id), ...countedShownIds])
                return Math.max(moreReports.count - visible.size, 0)
            },
        ],
        // While a newer briefing is written, the server returns the shown one as `writing`, so the
        // text stays on screen and the page keeps asking until the new one is ready.
        briefingWaiting: [
            (s) => [s.personalBriefing, s.gaveUpWaitingFor, s.refreshedBriefingLoading, s.reloadingAfterRefresh],
            (
                personalBriefing: BriefingApi | null,
                gaveUpWaitingFor: string | null,
                refreshedBriefingLoading: boolean,
                reloadingAfterRefresh: boolean
            ): boolean =>
                refreshedBriefingLoading ||
                reloadingAfterRefresh ||
                (!!personalBriefing &&
                    personalBriefing.id !== gaveUpWaitingFor &&
                    !isBriefingSettled(personalBriefing)),
        ],
    }),
    listeners(({ actions, values, cache }) => {
        const schedulePoll = (): void => {
            cache.disposables.add(() => {
                const poll = window.setTimeout(() => actions.pollBriefing(), BRIEFING_POLL_MS)
                return () => clearTimeout(poll)
            }, 'briefingPoll')
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
                // An open tab moves to the new day's briefing at 8:00 without a reload, including a laptop
                // that slept through it. The first tick, at mount, only records the day.
                const day = briefingDayKey(values.now)
                if (cache.day !== undefined && day !== cache.day && !values.useSampleData) {
                    actions.loadPersonalBriefing()
                }
                cache.day = day
            },
            openReport: ({ report, source }) => {
                router.actions.push(urls.todayReport(report.id))
                actions.reportOpened(report, source)
            },
            setUseSampleData: ({ useSampleData }) => {
                actions.loadTopReports()
                if (!useSampleData) {
                    actions.loadPersonalBriefing()
                }
            },
            loadPersonalBriefingSuccess: ({ personalBriefing }) => {
                if (!personalBriefing) {
                    return
                }
                if (values.briefingWaiting) {
                    if (values.briefingPolls >= MAX_BRIEFING_POLLS) {
                        actions.stopWaitingForBriefing(personalBriefing.id)
                        return
                    }
                    schedulePoll()
                    return
                }
                if (cache.viewedBriefingId === personalBriefing.id) {
                    return
                }
                cache.viewedBriefingId = personalBriefing.id
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today briefing viewed', {
                    status: personalBriefing.status,
                    writer: personalBriefing.writer,
                    item_count: personalBriefing.items.length,
                    done_item_count: personalBriefing.items.filter((item) => item.state === 'done').length,
                    dismissed_item_count: personalBriefing.items.filter((item) => item.state === 'dismissed').length,
                    more_reports_count: personalBriefing.more_reports_count,
                })
            },
            loadPersonalBriefingFailure: ({ errorObject }) => {
                // A poll that fails while the briefing is written keeps polling; a 404 means there is no
                // briefing for this person, so the report list stays.
                const notFound = errorObject instanceof ApiError && errorObject.status === 404
                if (values.briefingWaiting && !notFound && values.briefingPolls < MAX_BRIEFING_POLLS) {
                    schedulePoll()
                }
            },
            pollBriefing: () => {
                actions.loadPersonalBriefing()
            },
            refreshBriefing: () => {
                // pinned: analytics event name. Renaming it breaks dashboards.
                posthog.capture('today refresh clicked', { writer: values.personalBriefing?.writer ?? null })
            },
            refreshBriefingSuccess: () => {
                actions.loadPersonalBriefing()
            },
            refreshBriefingFailure: ({ errorObject }) => {
                const detail = errorObject instanceof ApiError ? errorObject.detail : null
                lemonToast.error(detail || 'Couldn’t refresh your briefing. Try again in a minute.')
            },
            openItem: ({ item, surface }) => {
                const href = itemHref(item)
                if (isExternalHref(href)) {
                    window.open(href, '_blank', 'noopener')
                } else {
                    navigateToHref(href)
                }
                actions.itemOpened(item, surface)
            },
            itemOpened: ({ item, surface }) => {
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today item opened', {
                    group: item.group,
                    source: item.source,
                    reason: item.reason,
                    rank: item.rank,
                    state: item.state,
                    surface,
                })
            },
            reportPreviewed: ({ cardKey, surface }) => {
                const item = values.briefingItems.find((candidate) => candidate.key === cardKey)
                if (item) {
                    // pinned: analytics event name and properties. Renaming them breaks dashboards.
                    posthog.capture('today report previewed', {
                        list: 'personal',
                        source: item.source,
                        reason: item.reason,
                        rank: item.rank,
                        state: item.state,
                        has_metric: !!item.report?.metrics.length,
                        surface,
                    })
                    return
                }
                if (values.useSampleData) {
                    return
                }
                // The team list stays loaded under the personal briefing, but only the list on screen counts.
                for (const [list, reports] of [
                    ['team', values.showPersonalBriefing ? [] : values.reports],
                    ['more', values.sidebarMoreReports],
                ] as const) {
                    const rank = reports.findIndex((report) => teamReportCard(report).key === cardKey) + 1
                    if (rank > 0) {
                        posthog.capture('today report previewed', {
                            list,
                            rank,
                            has_metric: !!reports[rank - 1].metrics?.length,
                            surface,
                        })
                        return
                    }
                }
            },
            locationChanged: ({ searchParams }) => {
                const useSampleData = parseSampleParam(searchParams.sample)
                if (useSampleData !== null && useSampleData !== values.useSampleData) {
                    actions.setUseSampleData(useSampleData)
                }
            },
            loadTopReportsSuccess: ({ topReports }) => {
                if (values.useSampleData) {
                    return
                }
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today home loaded', {
                    report_count: topReports.results.length,
                    more_report_count: values.moreReportCount,
                })
            },
            requestReportVerdict: ({ target, verdict, surface }) => {
                if (!target.hasOpenPullRequest) {
                    actions.setReportVerdict(target, verdict, surface)
                    return
                }
                const copy = VERDICTS[verdict]
                LemonDialog.open({
                    title: copy.confirmTitle,
                    description: 'This also closes the open pull request for this report.',
                    primaryButton: {
                        children: copy.confirmLabel,
                        onClick: () => actions.setReportVerdict(target, verdict, surface),
                        'data-attr': `today-report-${verdict}-confirm`,
                    },
                    secondaryButton: { children: 'Cancel' },
                })
            },
            setReportVerdict: async ({ target, verdict, surface }) => {
                const copy = VERDICTS[verdict]
                try {
                    await signalsReportsStateCreate(String(values.currentProjectId), target.reportId, {
                        state: copy.apiState,
                    })
                } catch (error) {
                    actions.setReportVerdictFailure(target.reportId)
                    lemonToast.error((error instanceof ApiError && error.detail) || copy.failure)
                    return
                }
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today report state changed', {
                    verdict,
                    surface,
                    closed_pull_request: target.hasOpenPullRequest,
                })
                // A reason is optional, so the verdict is one click and the reason is one more.
                lemonToast.success(target.hasOpenPullRequest ? copy.successClosingPullRequest : copy.success, {
                    button: { label: 'Add a reason', action: () => actions.addReportVerdictReason(target, verdict) },
                })
            },
            // No confirm dialog: unlike a verdict, this changes nothing for anyone but the person.
            leaveReportReview: async ({ reportId, surface }) => {
                try {
                    await signalsReportsReviewersMeDestroy(String(values.currentProjectId), reportId)
                } catch (error) {
                    actions.leaveReportReviewFailure(reportId)
                    lemonToast.error(
                        (error instanceof ApiError && error.detail) ||
                            'Couldn’t remove you from the reviewers. Try again, or change them from the Inbox.'
                    )
                    return
                }
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today report review left', { surface })
                lemonToast.success('Removed you from the reviewers')
            },
            addReportVerdictReason: ({ target, verdict }) => {
                const copy = VERDICTS[verdict]
                const dialogCopy = {
                    title: copy.reasonTitle,
                    description: copy.reasonDescription,
                    submitLabel: 'Save reason',
                }
                // The state API takes the verdict the report already has and only saves the reason with it.
                const saveReason = async (body: SignalReportStateRequestApi): Promise<void> => {
                    try {
                        await signalsReportsStateCreate(String(values.currentProjectId), target.reportId, body)
                    } catch (error) {
                        lemonToast.error(
                            (error instanceof ApiError && error.detail) || 'Couldn’t save the reason. Try again.'
                        )
                        // The dialog stays open, so the reason and the note are kept for the next try.
                        throw error
                    }
                    // pinned: analytics event name and properties. Renaming them breaks dashboards.
                    posthog.capture('today report reason added', {
                        verdict,
                        reason: body.dismissal_reason,
                        has_note: !!body.dismissal_note,
                    })
                    lemonToast.success('Reason saved')
                }
                if (verdict === 'resolve') {
                    openResolveReportDialog({
                        reportTitle: target.title,
                        copy: dialogCopy,
                        onConfirm: ({ reason, note }) =>
                            saveReason({
                                state: copy.apiState,
                                dismissal_reason: reason,
                                ...(note ? { dismissal_note: note } : {}),
                            }),
                    })
                } else {
                    openDismissReportDialog({
                        reportTitle: target.title,
                        copy: dialogCopy,
                        onConfirm: (dismissal) =>
                            saveReason({ state: copy.apiState, ...suppressDismissalPayload(dismissal) }),
                    })
                }
            },
            loadMoreReports: () => {
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today more reports clicked', { shown_report_count: values.shownReportIds.length })
            },
            loadMoreReportsSuccess: () => {
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('today more reports loaded', {
                    report_count: values.sidebarMoreReports.length,
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
