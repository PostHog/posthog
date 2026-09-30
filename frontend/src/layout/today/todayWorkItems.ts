import { Dayjs, dayjs } from 'lib/dayjs'

import { ConversationDetail } from '~/types'

import { TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'

export type TodayWorkItemKind = 'session' | 'chat'

export interface TodayWorkItem {
    kind: TodayWorkItemKind
    id: string
    title: string
    timestamp: string | null
    status: string | null
    channel: string | null
    createdById: number | null
    latestRunId: string | null
    originProduct: string | null
}

export interface TodayWorkGroup {
    key: string
    label: string
    items: TodayWorkItem[]
}

const FINISHED_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export function canHandOff(item: TodayWorkItem, userId: number | null | undefined): boolean {
    return item.kind === 'session' && item.createdById !== null && item.createdById === userId
}

export function analysisRunId(item: TodayWorkItem): string | null {
    return item.originProduct !== 'task_analysis' && item.status !== null && FINISHED_RUN_STATUSES.has(item.status)
        ? item.latestRunId
        : null
}

export function sessionItem(task: TaskListItemApi): TodayWorkItem {
    return {
        kind: 'session',
        id: task.id,
        title: task.title,
        timestamp: task.last_activity_at ?? task.updated_at ?? task.created_at ?? null,
        status: task.latest_run?.status ?? null,
        channel: task.channel ?? null,
        createdById: task.created_by?.id ?? null,
        latestRunId: task.latest_run?.id ?? null,
        originProduct: task.origin_product ?? null,
    }
}

export function chatItem(conversation: ConversationDetail): TodayWorkItem {
    return {
        kind: 'chat',
        id: conversation.id,
        title: conversation.title ?? '',
        timestamp: conversation.updated_at ?? conversation.created_at,
        status: null,
        channel: null,
        createdById: null,
        latestRunId: null,
        originProduct: null,
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

export function groupByDay(items: TodayWorkItem[], now: Dayjs = dayjs()): TodayWorkGroup[] {
    const groups: TodayWorkGroup[] = []
    for (const item of items) {
        const time = item.timestamp ? earlierOf(dayjs(item.timestamp), now) : null
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
