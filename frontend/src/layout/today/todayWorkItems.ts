import { Dayjs, dayjs } from 'lib/dayjs'
import { fullNameOrEmail } from 'lib/utils/strings'

import { ConversationDetail } from '~/types'

import { TaskListItemApi, TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'
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
    createdByName: string | null
    latestRunId: string | null
    runEnvironment: string | null
    originProduct: string | null
    /** What filed it: a session's origin product, or PostHog AI for a chat. */
    source: string | null
    repository: string | null
    pullRequests: TaskPullRequest[]
    /** The closing message of the last turn the run finished, in one line. */
    lastMessage: string | null
}

export interface TodayWorkGroup {
    key: string
    label: string
    items: TodayWorkItem[]
}

const LAST_MESSAGE_MAX_CHARS = 240

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
        createdByName: task.created_by ? fullNameOrEmail(task.created_by) : null,
        latestRunId: task.latest_run?.id ?? null,
        runEnvironment: task.latest_run?.environment ?? null,
        originProduct: task.origin_product ?? null,
        source: task.origin_product || null,
        repository: task.repository || null,
        pullRequests: taskPullRequests(task.latest_run?.output),
        lastMessage: lastRunMessage(task.latest_run?.output),
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
        createdByName: conversation.user ? fullNameOrEmail(conversation.user) : null,
        latestRunId: null,
        runEnvironment: null,
        originProduct: null,
        source: 'posthog_ai',
        repository: null,
        pullRequests: [],
        lastMessage: null,
    }
}

export function lastRunMessage(output: TaskRunDetailDTOApi['output'] | undefined): string | null {
    const message = output?.final_message
    if (typeof message !== 'string') {
        return null
    }
    const collapsed = message.replace(/\s+/g, ' ').trim()
    if (collapsed.length <= LAST_MESSAGE_MAX_CHARS) {
        return collapsed || null
    }
    const cut = collapsed.slice(0, LAST_MESSAGE_MAX_CHARS)
    const lastSpace = cut.lastIndexOf(' ')
    return `${(lastSpace > LAST_MESSAGE_MAX_CHARS / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`
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
