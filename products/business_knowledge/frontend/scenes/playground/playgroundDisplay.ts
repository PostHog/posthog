import { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import {
    type BusinessKnowledgeDocumentsSearchListParams,
    type BusinessKnowledgeDocumentsWindowListParams,
    type KnowledgeSearchResultApi,
    type PlaygroundChatListApi,
    type SandboxSearchApi,
    SandboxToolNameEnumApi,
} from '../../generated/api.schemas'

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

export type PlaygroundCitationRequest =
    | { kind: 'search'; params: BusinessKnowledgeDocumentsSearchListParams }
    | { kind: 'window'; documentId: string; params: BusinessKnowledgeDocumentsWindowListParams }

export function errorDetail(error: unknown, fallback: string): string {
    if (error instanceof ApiError && error.detail) {
        return error.detail
    }
    return fallback
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
    if (search.tool === SandboxToolNameEnumApi.BusinessKnowledgeRepositoriesSearch) {
        const query = typeof args?.query === 'string' ? args.query : null
        return { title: 'Searched repositories', subtitle: query ?? (args ? null : search.input) }
    }
    if (search.tool === SandboxToolNameEnumApi.BusinessKnowledgeRepositoriesFileRetrieve) {
        const repo = typeof args?.repo === 'string' ? args.repo : ''
        const filePath = typeof args?.path === 'string' ? args.path : ''
        const subtitle = repo && filePath ? `${repo}/${filePath}` : null
        return { title: 'Read file', subtitle: subtitle ?? (args ? null : search.input) }
    }
    return { title: 'Read document context', subtitle: args ? null : search.input }
}

/** Folded trace subtitle, such as "2 searches, 1 read". Null before the first call. */
export function summarizeSearches(searches: SandboxSearchApi[]): string | null {
    const reads = searches.filter(
        (search) =>
            search.tool === SandboxToolNameEnumApi.BusinessKnowledgeDocumentWindowRetrieve ||
            search.tool === SandboxToolNameEnumApi.BusinessKnowledgeRepositoriesFileRetrieve
    ).length
    const lookups = searches.length - reads
    const parts = [
        lookups > 0 ? `${lookups} ${lookups === 1 ? 'search' : 'searches'}` : null,
        reads > 0 ? `${reads} ${reads === 1 ? 'read' : 'reads'}` : null,
    ].filter((part): part is string => part !== null)
    return parts.length > 0 ? parts.join(', ') : null
}

/** Source refs are free text the agent writes, so this matches loosely on source and document names. */
export function isCitedChunk(
    chunk: Pick<KnowledgeSearchResultApi, 'source_name' | 'document_title'>,
    refs: string[]
): boolean {
    const names = [chunk.source_name, chunk.document_title].map((name) => name.trim().toLowerCase()).filter(Boolean)
    return refs.some((ref) => {
        const needle = ref.trim().toLowerCase()
        return needle !== '' && names.some((name) => needle.includes(name) || name.includes(needle))
    })
}

/** The request that fetches the chunks a document search or window read returned. Null for other tools. */
export function citationRequest(search: SandboxSearchApi): PlaygroundCitationRequest | null {
    const args = searchArguments(search)
    if (search.tool === SandboxToolNameEnumApi.BusinessKnowledgeDocumentsSearch && typeof args?.query === 'string') {
        return {
            kind: 'search',
            params: {
                query: args.query,
                ...(typeof args.limit === 'number' ? { limit: args.limit } : {}),
                ...(typeof args.rerank === 'boolean' ? { rerank: args.rerank } : {}),
                ...(typeof args.library_id === 'string' ? { library_id: args.library_id } : {}),
            },
        }
    }
    if (
        search.tool === SandboxToolNameEnumApi.BusinessKnowledgeDocumentWindowRetrieve &&
        typeof args?.id === 'string' &&
        typeof args.around_ordinal === 'number'
    ) {
        return {
            kind: 'window',
            documentId: args.id,
            params: {
                around_ordinal: args.around_ordinal,
                ...(typeof args.radius === 'number' ? { radius: args.radius } : {}),
            },
        }
    }
    return null
}
