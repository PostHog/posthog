import { Dayjs, dayjs } from 'lib/dayjs'

import { ConversationDetail } from '~/types'

import {
    TaskActivityDTOApi,
    TaskActivityReadMarkerApi,
    TaskListItemApi,
} from 'products/tasks/frontend/generated/api.schemas'
import { TaskPullRequest, taskPullRequests } from 'products/tasks/frontend/spaces/taskPullRequests'

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
    latestRunId: string | null
    runEnvironment: string | null
    originProduct: string | null
    /** What filed it: a session's origin product, or PostHog AI for a chat. */
    source: string | null
    repository: string | null
    pullRequests: TaskPullRequest[]
}

export interface TodayWorkGroup {
    key: string
    label: string
    items: TodayWorkItem[]
}

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
        latestRunId: task.latest_run?.id ?? null,
        runEnvironment: task.latest_run?.environment ?? null,
        originProduct: task.origin_product ?? null,
        source: task.origin_product || null,
        repository: task.repository || null,
        pullRequests: taskPullRequests(task.latest_run?.output),
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
        latestRunId: null,
        runEnvironment: null,
        originProduct: null,
        source: 'posthog_ai',
        repository: null,
        pullRequests: [],
    }
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
