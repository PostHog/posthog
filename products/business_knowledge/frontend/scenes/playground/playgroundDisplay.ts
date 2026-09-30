import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { type PlaygroundChatListApi, type SandboxSearchApi, SandboxToolNameEnumApi } from '../../generated/api.schemas'

const DATE_GROUP_ORDER = ['Today', 'Yesterday', 'Last 7 days', 'Last 30 days', 'Older'] as const

export type PlaygroundChatGroupLabel = (typeof DATE_GROUP_ORDER)[number]

export interface PlaygroundChatGroup {
    label: PlaygroundChatGroupLabel
    chats: PlaygroundChatListApi[]
}

export interface PlaygroundSearchLabel {
    title: string
    subtitle: string | null
}

function dateGroupLabel(iso: string, now: dayjs.Dayjs): PlaygroundChatGroupLabel {
    const date = dayjs(iso)
    const today = now.startOf('day')
    if (!date.isBefore(today)) {
        return 'Today'
    }
    if (!date.isBefore(today.subtract(1, 'day'))) {
        return 'Yesterday'
    }
    if (!date.isBefore(today.subtract(7, 'day'))) {
        return 'Last 7 days'
    }
    if (!date.isBefore(today.subtract(30, 'day'))) {
        return 'Last 30 days'
    }
    return 'Older'
}

/** Same buckets and order as the PostHog AI chat list, newest activity first. */
export function groupPlaygroundChats(
    chats: PlaygroundChatListApi[],
    search: string,
    now: dayjs.Dayjs = dayjs()
): PlaygroundChatGroup[] {
    const needle = search.trim().toLowerCase()
    const matching = needle ? chats.filter((chat) => chat.title.toLowerCase().includes(needle)) : chats
    const sorted = [...matching].sort((left, right) => dayjs(right.updated_at).diff(dayjs(left.updated_at)))
    const grouped = new Map<PlaygroundChatGroupLabel, PlaygroundChatListApi[]>()
    for (const chat of sorted) {
        const label = dateGroupLabel(chat.updated_at, now)
        grouped.set(label, [...(grouped.get(label) ?? []), chat])
    }
    return DATE_GROUP_ORDER.flatMap((label) => {
        const group = grouped.get(label)
        return group ? [{ label, chats: group }] : []
    })
}

export function formatChatAge(iso: string): string {
    const seconds = dayjs().diff(dayjs(iso), 'second')
    return seconds < 60 ? 'now' : humanFriendlyDuration(seconds, { maxUnits: 1 })
}

function searchArguments(search: SandboxSearchApi): Record<string, unknown> | null {
    // Single-exec calls arrive as `call <tool> {json}`; direct calls arrive as the JSON input.
    const json = search.input.startsWith(`call ${search.tool}`)
        ? search.input.slice(`call ${search.tool}`.length).trim()
        : search.input
    try {
        const parsed: unknown = JSON.parse(json)
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : null
    } catch {
        return null
    }
}

export function describeSearch(search: SandboxSearchApi): PlaygroundSearchLabel {
    const args = searchArguments(search)
    if (search.tool === SandboxToolNameEnumApi.BusinessKnowledgeDocumentsSearch) {
        const query = typeof args?.query === 'string' ? args.query : null
        return { title: 'Searched business knowledge', subtitle: query ?? (args ? null : search.input) }
    }
    return { title: 'Read document context', subtitle: args ? null : search.input }
}
