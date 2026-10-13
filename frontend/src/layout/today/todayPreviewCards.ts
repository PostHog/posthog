import { getOriginProductMeta } from 'products/posthog_ai/frontend/api/taskSource'
import type { ReportChartApi, ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'
import { PrStateEnumApi, TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'
import { TaskPullRequest } from 'products/tasks/frontend/spaces/taskPullRequests'

import { recentSourceLabel } from './todayRecentFilters'
import { TodaySessionDot, todaySessionDot } from './todaySessionDot'
import { TodaySessionMenuTarget, TodayWorkItem, sessionMenuTarget } from './todayWorkItems'

/** What a session row's hover card says, built once per row so the shared card gets a stable payload. */
export interface TodaySessionPreview {
    kind: 'session'
    title: string
    dot: TodaySessionDot
    pinned: boolean
    pullRequest: TaskPullRequest | null
    pullRequestState: PrStateEnumApi | null
    spaceName: string | null
    repository: string | null
    branch: string | null
    /** What filed the session, or null when a person made it by hand. */
    source: string | null
    /** The source product's icon, for the origins that have one. */
    sourceIcon: JSX.Element | null
    author: TaskUserBasicInfoApi | null
    timestamp: string | null
    message: string | null
    menu: TodaySessionMenuTarget
}

export interface TodayChatPreview {
    kind: 'chat'
    chatId: string
    title: string
    source: string
    timestamp: string | null
}

/** What a report's hover card says, read from a personal briefing item or from one of the team's reports. */
export interface TodayReportCard {
    /** Stable per report and list. It keys the card's live metric queries and its analytics. */
    key: string
    /** The report the card's resolve and dismiss buttons act on, or null when the card has no report. */
    reportId: string | null
    title: string
    /** Why the briefing picked the report. Null for the team's reports, which no briefing picked. */
    reason: string | null
    /** Resolved or dismissed since the briefing, or null while open. */
    stateLabel: string | null
    resolved: boolean
    /** Whether the person is one of the report's suggested reviewers, and so can step off it. */
    canLeaveReview: boolean
    priority: string | null
    summary: string | null
    pullRequestState: PrStateEnumApi | null
    pullRequestUrl: string | null
    signalCount: number | null
    updatedAt: string | null
    metrics: ReportMetricApi[]
    /** Charts from the report body. The card draws one when no metric has a chart. */
    charts: ReportChartApi[]
    sourceLabel: string
}

/** A report's hover card. The card text comes with the page, so it opens without a request. */
export interface TodayReportPreview {
    kind: 'report'
    card: TodayReportCard
    /** Where the card opened: a link in the briefing text, or a left-bar row. */
    surface: 'briefing' | 'sidebar'
}

export type TodayPreviewPayload = TodaySessionPreview | TodayChatPreview | TodayReportPreview

export function sessionPreview(
    item: TodayWorkItem,
    {
        unread,
        pinned,
        pullRequestStates,
        spaceNames,
        menuId,
        userId,
    }: {
        unread: boolean
        pinned: boolean
        pullRequestStates: Record<string, PrStateEnumApi>
        spaceNames: Record<string, string>
        menuId: string
        userId: number | null | undefined
    }
): TodaySessionPreview {
    // The row shows only the first pull request, so the card names the same one.
    const [pullRequest] = item.pullRequests
    return {
        kind: 'session',
        title: item.title || 'Untitled session',
        dot: todaySessionDot(item, unread),
        pinned,
        pullRequest: pullRequest ?? null,
        pullRequestState: pullRequest ? (pullRequestStates[pullRequest.url] ?? null) : null,
        spaceName: item.channel ? (spaceNames[item.channel] ?? null) : null,
        repository: item.repository,
        branch: item.branch,
        source:
            item.originProduct && item.originProduct !== 'user_created' ? recentSourceLabel(item.originProduct) : null,
        sourceIcon: getOriginProductMeta(item.originProduct ?? undefined)?.icon ?? null,
        author: item.author,
        timestamp: item.timestamp,
        message: item.finalMessage,
        menu: sessionMenuTarget(item, { menuId, pinned, userId }),
    }
}

export function chatPreview(item: TodayWorkItem): TodayChatPreview {
    return {
        kind: 'chat',
        chatId: item.id,
        title: item.title || 'Untitled chat',
        source: 'PostHog AI',
        timestamp: item.timestamp,
    }
}
