import { Dayjs, dayjs } from 'lib/dayjs'

import { ConversationDetail } from '~/types'

import {
    TaskActivityDTOApi,
    TaskActivityReadMarkerApi,
    TaskListItemApi,
    TaskRunDetailDTOApi,
    TaskUserBasicInfoApi,
} from 'products/tasks/frontend/generated/api.schemas'
import { presenceTier } from 'products/tasks/frontend/spaces/spacePresence'
import { TaskPullRequest, taskPullRequests } from 'products/tasks/frontend/spaces/taskPullRequests'
import { taskUserName } from 'products/tasks/frontend/spaces/TaskUserAvatar'

import { TodayListItemDetail, TodayListItemField, listItemDetails } from './todayListAppearance'

export type TodayWorkItemKind = 'session' | 'chat'

export interface TodayWorkItem {
    kind: TodayWorkItemKind
    id: string
    title: string
    timestamp: string | null
    createdAt: string | null
    status: string | null
    channel: string | null
    createdById: number | null
    author: TaskUserBasicInfoApi | null
    latestRunId: string | null
    runEnvironment: string | null
    originProduct: string | null
    /** What filed it: a session's origin product, or PostHog AI for a chat. */
    source: string | null
    repository: string | null
    /** The latest run's branch. */
    branch: string | null
    pullRequests: TaskPullRequest[]
    /** The closing prose a cloud run saves when it finishes. */
    finalMessage: string | null
}

export interface TodayWorkGroup {
    key: string
    label: string
    items: TodayWorkItem[]
}

export type TodaySessionBadge =
    | { kind: 'author'; author: TaskUserBasicInfoApi; live: boolean }
    | { kind: 'source'; source: string }
    | { kind: 'pullRequest'; pullRequest: TaskPullRequest }
    | { kind: 'local' }

const BADGE_SOURCES = new Set([
    'slack',
    'signal_report',
    'signals_scout',
    'support_queue',
    'session_summaries',
    'error_tracking',
    'eval_clusters',
    'task_analysis',
])

const MAX_ROW_BADGES = 3

const FINISHED_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const ACTIVE_RUN_STATUSES = new Set(['not_started', 'queued', 'in_progress'])

export function canHandOff(item: TodayWorkItem, userId: number | null | undefined): boolean {
    return item.kind === 'session' && item.createdById !== null && item.createdById === userId
}

export function analysisRunId(item: TodayWorkItem): string | null {
    return item.originProduct !== 'task_analysis' && item.status !== null && FINISHED_RUN_STATUSES.has(item.status)
        ? item.latestRunId
        : null
}

/** The latest run when it is a cloud run that is still going, so the session can be stopped. */
export function activeCloudRunId(item: TodayWorkItem): string | null {
    return item.kind === 'session' &&
        item.runEnvironment === 'cloud' &&
        item.status !== null &&
        ACTIVE_RUN_STATUSES.has(item.status)
        ? item.latestRunId
        : null
}

/** What a session's menus and its hover card act on. */
export interface TodaySessionMenuTarget {
    /** The row or card that owns the follow-up dialogs, so they outlive the menu that opened them. */
    menuId: string
    sessionId: string
    title: string
    pinned: boolean
    spaceId: string | null
    canHandOff: boolean
    analysisRunId: string | null
    /** The latest run while it is an active cloud run: it can be stopped, and archiving asks first. */
    activeRunId: string | null
}

export function sessionMenuTarget(
    item: TodayWorkItem,
    { menuId, pinned, userId }: { menuId: string; pinned: boolean; userId: number | null | undefined }
): TodaySessionMenuTarget {
    return {
        menuId,
        sessionId: item.id,
        title: item.title,
        pinned,
        spaceId: item.channel,
        canHandOff: canHandOff(item, userId),
        analysisRunId: analysisRunId(item),
        activeRunId: activeCloudRunId(item),
    }
}

function finalMessage(output: TaskRunDetailDTOApi['output'] | undefined): string | null {
    const message = output?.final_message
    return typeof message === 'string' && message.trim() ? message.trim() : null
}

/** What the session icon reads, from a task's latest run, for a page that has the task but not its work item. */
export function sessionIconFields(
    latestRun: { status?: string | null; environment?: string | null } | null | undefined
): Pick<TodayWorkItem, 'kind' | 'status' | 'runEnvironment'> {
    return { kind: 'session', status: latestRun?.status ?? null, runEnvironment: latestRun?.environment ?? null }
}

export function sessionItem(task: TaskListItemApi): TodayWorkItem {
    return {
        kind: 'session',
        id: task.id,
        title: task.title,
        timestamp: task.last_activity_at ?? task.updated_at ?? task.created_at ?? null,
        createdAt: task.created_at ?? null,
        status: task.latest_run?.status ?? null,
        channel: task.channel ?? null,
        createdById: task.created_by?.id ?? null,
        author: task.created_by ?? null,
        latestRunId: task.latest_run?.id ?? null,
        runEnvironment: task.latest_run?.environment ?? null,
        originProduct: task.origin_product ?? null,
        source: task.origin_product || null,
        repository: task.repository || null,
        branch: task.latest_run?.branch || null,
        pullRequests: taskPullRequests(task.latest_run?.output),
        finalMessage: finalMessage(task.latest_run?.output),
    }
}

export function chatItem(conversation: ConversationDetail): TodayWorkItem {
    return {
        kind: 'chat',
        id: conversation.id,
        title: conversation.title ?? '',
        timestamp: conversation.updated_at ?? conversation.created_at,
        createdAt: conversation.created_at,
        status: null,
        channel: null,
        createdById: conversation.user?.id ?? null,
        author: null,
        latestRunId: null,
        runEnvironment: null,
        originProduct: null,
        source: 'posthog_ai',
        repository: null,
        branch: null,
        pullRequests: [],
        finalMessage: null,
    }
}

export function sessionBadges(
    item: TodayWorkItem,
    userId: number | null | undefined,
    { pinned = false, now = Date.now() }: { pinned?: boolean; now?: number } = {}
): TodaySessionBadge[] {
    const badges: TodaySessionBadge[] = []
    if (item.originProduct && BADGE_SOURCES.has(item.originProduct)) {
        badges.push({ kind: 'source', source: item.originProduct })
    }
    const [pullRequest] = item.pullRequests
    if (pullRequest) {
        badges.push({ kind: 'pullRequest', pullRequest })
    }
    if (badges.length === 0 && item.runEnvironment === 'local') {
        badges.push({ kind: 'local' })
    }
    const activityAt = item.timestamp ? Date.parse(item.timestamp) : Number.NaN
    const tier = Number.isNaN(activityAt) ? 'idle' : presenceTier(activityAt, now)
    if (item.author && item.createdById !== userId && tier !== 'idle') {
        badges.unshift({ kind: 'author', author: item.author, live: tier === 'live' })
    }
    if (badges.length + (pinned ? 1 : 0) > MAX_ROW_BADGES) {
        return badges.filter((badge) => badge.kind !== 'source')
    }
    return badges
}

/** "2h ago", with the exact time for the tooltip. The same scale as PostHog Desktop's row details. */
export function activityDetail(
    timestamp: string | null,
    now: Dayjs = dayjs()
): Omit<TodayListItemDetail, 'field'> | null {
    if (!timestamp) {
        return null
    }
    const age = shortTimeAgo(timestamp, now)
    return { text: age === 'now' ? 'just now' : `${age} ago`, title: dayjs(timestamp).format('LLL') }
}

/** The second line under a session row's title, in the order the person chose. */
export function sessionDetails(
    item: TodayWorkItem,
    fields: readonly TodayListItemField[],
    spaceNames: Record<string, string>,
    now: Dayjs = dayjs()
): TodayListItemDetail[] {
    if (!fields.length) {
        return []
    }
    return listItemDetails(
        {
            space: item.channel ? spaceNames[item.channel] : null,
            repository: item.repository,
            branch: item.branch,
            creator: item.author ? taskUserName(item.author) : null,
            activity: activityDetail(item.timestamp, now),
        },
        fields
    )
}

export function buildRecentItems(
    sessions: TaskListItemApi[],
    chats: ConversationDetail[],
    pinnedSessionIds: string[],
    limit: number
): TodayWorkItem[] {
    const pinned = new Set(pinnedSessionIds)
    return [
        ...sessions.filter((task) => !pinned.has(task.id) && !task.archived).map(sessionItem),
        ...chats.map(chatItem),
    ]
        .sort((first, second) => timeOf(second) - timeOf(first))
        .slice(0, limit)
}

export interface TodaySessionReadRequest {
    marker: TaskActivityReadMarkerApi
    activityIds: string[]
}

// Comment notifications clear per comment, not per session, so only a session's own activity marks it unread.
function unreadSessionActivity(activity: TaskActivityDTOApi[], sessionId?: string): TaskActivityDTOApi[] {
    return activity.filter(
        (row) => row.is_unread && !!row.task_id && !row.latest_comment_id && (!sessionId || row.task_id === sessionId)
    )
}

export function unreadSessionIds(activity: TaskActivityDTOApi[]): Set<string> {
    return new Set(unreadSessionActivity(activity).map((row) => row.task_id as string))
}

export function unreadSpaceIds(activity: TaskActivityDTOApi[]): Set<string> {
    return new Set(unreadSessionActivity(activity).flatMap((row) => (row.channel_id ? [row.channel_id] : [])))
}

export function unreadSessionCountsBySpace(activity: TaskActivityDTOApi[]): Record<string, number> {
    const sessionsBySpace: Record<string, Set<string>> = {}
    for (const row of unreadSessionActivity(activity)) {
        if (row.channel_id) {
            sessionsBySpace[row.channel_id] ??= new Set()
            sessionsBySpace[row.channel_id].add(row.task_id as string)
        }
    }
    return Object.fromEntries(Object.entries(sessionsBySpace).map(([spaceId, sessions]) => [spaceId, sessions.size]))
}

/**
 * What to send to mark a session read, or null when it has nothing unread.
 * `seen_before` is never earlier than the newest activity shown, so a client clock behind the server's still clears it.
 */
export function sessionReadRequest(
    activity: TaskActivityDTOApi[],
    sessionId: string,
    now: Dayjs = dayjs()
): TodaySessionReadRequest | null {
    const rows = unreadSessionActivity(activity, sessionId)
    if (!rows.length) {
        return null
    }
    const seenBefore = rows.reduce(
        (latest, row) => (dayjs(row.activity_at).isAfter(latest) ? dayjs(row.activity_at) : latest),
        now
    )
    return {
        marker: { task_id: sessionId, seen_before: seenBefore.toISOString() },
        activityIds: rows.map((row) => row.id),
    }
}

export function setActivityUnread(
    activity: TaskActivityDTOApi[],
    activityIds: string[],
    isUnread: boolean
): TaskActivityDTOApi[] {
    const ids = new Set(activityIds)
    return activity.map((row) => (ids.has(row.id) ? { ...row, is_unread: isUnread } : row))
}

export function groupByDay(
    items: TodayWorkItem[],
    now: Dayjs = dayjs(),
    timeField: 'timestamp' | 'createdAt' = 'timestamp'
): TodayWorkGroup[] {
    const groups: TodayWorkGroup[] = []
    for (const item of items) {
        const timestamp = item[timeField]
        const time = timestamp ? earlierOf(dayjs(timestamp), now) : null
        const key = time ? time.format('YYYY-MM-DD') : 'undated'
        const last = groups[groups.length - 1]
        if (last?.key === key) {
            last.items.push(item)
        } else {
            groups.push({ key, label: time ? dayLabel(time, now) : 'Earlier', items: [item] })
        }
    }
    return groups
}

export function dayLabel(time: Dayjs, now: Dayjs = dayjs()): string {
    const days = now.startOf('day').diff(time.startOf('day'), 'day')
    if (days <= 0) {
        return 'Today'
    }
    if (days === 1) {
        return 'Yesterday'
    }
    if (days < 7) {
        return time.format('dddd')
    }
    return time.year() === now.year() ? time.format('MMM D') : time.format('MMM D, YYYY')
}

export function shortTimeAgo(timestamp: string | null, now: Dayjs = dayjs()): string {
    if (!timestamp) {
        return ''
    }
    const minutes = Math.max(0, now.diff(dayjs(timestamp), 'minute'))
    if (minutes < 1) {
        return 'now'
    }
    if (minutes < 60) {
        return `${minutes}m`
    }
    if (minutes < 60 * 24) {
        return `${Math.floor(minutes / 60)}h`
    }
    const days = Math.floor(minutes / (60 * 24))
    if (days < 7) {
        return `${days}d`
    }
    if (days < 30) {
        return `${Math.floor(days / 7)}w`
    }
    if (days < 365) {
        return `${Math.floor(days / 30)}mo`
    }
    return `${Math.floor(days / 365)}y`
}

function earlierOf(first: Dayjs, second: Dayjs): Dayjs {
    return first.isAfter(second) ? second : first
}

function timeOf(item: TodayWorkItem): number {
    return item.timestamp ? dayjs(item.timestamp).valueOf() : 0
}
