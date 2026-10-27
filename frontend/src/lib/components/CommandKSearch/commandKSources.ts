import api, { isAbortError } from 'lib/api'
import {
    SearchItem,
    accountToSearchItem,
    fileSystemEntryToSearchItem,
    groupToSearchItem,
    personToSearchItem,
    ticketToSearchItem,
    unifiedSearchResultToSearchItem,
} from 'lib/components/Search/searchItems'
import { shouldSearchTickets } from 'lib/components/Search/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { mapGroupQueryResponse } from 'lib/utils/groups'

import { fileSystemSearchRetrieve } from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'
import { isFileSystemEntryTypeEnabled } from '~/layout/panel-layout/ProjectTree/utils'
import type { Noun } from '~/models/groupsModel'
import type { FileSystemEntry } from '~/queries/schema/schema-general'
import { GroupType, GroupTypeIndex } from '~/types'

import { conversationsTicketsList } from 'products/conversations/frontend/generated/api'
import { accountsList } from 'products/customer_analytics/frontend/generated/api'
import { personsList } from 'products/persons/frontend/generated/api'

import { freeWords } from './commandKRanking'

export const RESULTS_LIMIT = 20
export const REQUEST_DEADLINE_MS = 3000
// An AbortError, so the API layer treats it like any cancelled request and reports nothing.
const DEADLINE_PASSED = new DOMException('The request deadline passed', 'AbortError')
export const SECONDARY_LIMIT = 5
const RANKED_RESULTS_LIMIT = 40
const RANKED_PER_TYPE = 4

/**
 * Remote sections, in render order. Results holds the objects that filters apply to. The rest
 * search free text for what the file system does not hold, and render below everything else.
 */
export const REMOTE_SOURCES = [
    'results',
    'events',
    'properties',
    'workflows',
    'accounts',
    'tickets',
    'persons',
    'groups',
] as const
export type RemoteSource = (typeof REMOTE_SOURCES)[number]

export type RemoteResults = Partial<Record<RemoteSource, SearchItem[]>>

export interface RemoteContext {
    currentTeamId: number | null
    groupTypes: GroupType[]
    aggregationLabel: (groupTypeIndex: GroupTypeIndex) => Noun
    customerAnalyticsEnabled: boolean
}

export interface RemoteRequest {
    id: string
    /** `objects` searches with filters applied. `text` searches the free text and runs only while no filter is set. */
    query: 'objects' | 'text'
    /** The sections this request fills. One request can fill several. */
    sources: RemoteSource[]
    enabled?: (query: string, context: RemoteContext) => boolean
    fetch: (query: string, signal: AbortSignal, context: RemoteContext) => Promise<RemoteResults>
}

const fetchPersons = async (term: string, signal: AbortSignal, context: RemoteContext): Promise<RemoteResults> => {
    const clientQueryId = uuid()
    let finished = false
    // Aborting the request does not stop the ClickHouse query, so cancel it by id.
    const cancel = (): void => {
        if (!finished) {
            api.cancelQuery(clientQueryId).catch(() => {})
        }
    }
    signal.addEventListener('abort', cancel, { once: true })
    try {
        const response = await personsList(
            String(context.currentTeamId),
            { search: term, limit: SECONDARY_LIMIT, client_query_id: clientQueryId },
            { signal }
        )
        return { persons: (response.results ?? []).filter((person) => !!person.uuid).map(personToSearchItem) }
    } finally {
        finished = true
        signal.removeEventListener('abort', cancel)
    }
}

const fetchGroups = async (term: string, signal: AbortSignal, context: RemoteContext): Promise<RemoteResults> => {
    const settled = await Promise.allSettled(
        context.groupTypes.map((groupType) =>
            // The generated groupsList is a different endpoint (Postgres REST). This ClickHouse
            // GroupsQuery matches what the current palette searches, so results stay the same.
            // nosemgrep: prefer-codegen-api-namespaced-groups
            api.groups.listClickhouse(
                { group_type_index: groupType.group_type_index, search: term, limit: SECONDARY_LIMIT },
                { signal }
            )
        )
    )
    // At the deadline, the group types that already answered still show.
    if (signal.reason !== DEADLINE_PASSED) {
        signal.throwIfAborted()
    }
    return {
        groups: settled.flatMap((result, index) => {
            if (result.status !== 'fulfilled') {
                return []
            }
            const groupTypeIndex = context.groupTypes[index].group_type_index as GroupTypeIndex
            const noun = context.aggregationLabel(groupTypeIndex).singular
            return mapGroupQueryResponse(result.value).map((group) => groupToSearchItem(group, groupTypeIndex, noun))
        }),
    }
}

const toFileSystemEntry = (entry: FileSystemApi): FileSystemEntry => ({
    id: entry.id,
    path: entry.path,
    type: entry.type,
    ref: entry.ref ?? undefined,
    href: entry.href ?? undefined,
    created_at: entry.created_at,
    last_viewed_at: entry.last_viewed_at,
    shortcut: entry.shortcut ?? undefined,
    user_access_level: entry.user_access_level,
})

const withCreator = (item: SearchItem, entry: FileSystemApi): SearchItem =>
    entry.created_by?.first_name ? { ...item, createdByName: entry.created_by.first_name } : item

const fetchRankedResults = async (
    search: string,
    signal: AbortSignal,
    context: RemoteContext,
    featureFlags: Record<string, unknown>
): Promise<SearchItem[]> => {
    const response = await fileSystemSearchRetrieve(
        String(context.currentTeamId),
        { search, limit: RANKED_RESULTS_LIMIT, per_type: RANKED_PER_TYPE },
        { signal }
    )
    const typeCounts = new Map(response.type_counts.map(({ type, count }) => [type, count]))
    return response.results
        .filter(({ entry }) => isFileSystemEntryTypeEnabled(entry, featureFlags))
        .map(({ entry, rank }) => ({
            ...withCreator(
                fileSystemEntryToSearchItem(toFileSystemEntry(entry), { id: entry.id, category: 'results' }),
                entry
            ),
            rankKey: rank,
            searchMatch: {
                matchedAllWords: response.matched_all_words,
                matchedWords: response.matched_words,
                typeCount: typeCounts.get(entry.type ?? '') ?? 0,
                countsCapped: response.counts_capped,
                withTypos: response.matched_with_typos,
            },
        }))
}

const UNIFIED_TYPES: Record<string, RemoteSource> = {
    event_definition: 'events',
    property_definition: 'properties',
    hog_flow: 'workflows',
}

export const REMOTE_REQUESTS: RemoteRequest[] = [
    {
        id: 'objects',
        query: 'objects',
        sources: ['results'],
        fetch: async (search, signal, context) => {
            const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags ?? {}
            if (freeWords(search).length > 0) {
                return { results: await fetchRankedResults(search, signal, context, featureFlags) }
            }
            const response = await api.fileSystem.list({ search, limit: RESULTS_LIMIT, notType: 'folder', signal })
            return {
                results: response.results
                    .filter((entry) => isFileSystemEntryTypeEnabled(entry, featureFlags))
                    .map((entry) => fileSystemEntryToSearchItem(entry, { id: entry.id, category: 'results' })),
            }
        },
    },
    {
        id: 'unified',
        query: 'text',
        sources: ['events', 'properties', 'workflows'],
        fetch: async (q, signal) => {
            const response = await api.search.list(
                { q, entities: ['event_definition', 'property_definition', 'hog_flow'], include_counts: false },
                { signal }
            )
            const results: RemoteResults = { events: [], properties: [], workflows: [] }
            for (const result of response.results) {
                const source = UNIFIED_TYPES[result.type]
                results[source]?.push(unifiedSearchResultToSearchItem(result))
            }
            return results
        },
    },
    {
        id: 'accounts',
        query: 'text',
        sources: ['accounts'],
        enabled: (_, context) => context.customerAnalyticsEnabled,
        fetch: async (search, signal, context) => {
            const response = await accountsList(
                String(context.currentTeamId),
                { search, limit: SECONDARY_LIMIT },
                { signal }
            )
            return { accounts: response.results.map(accountToSearchItem) }
        },
    },
    {
        id: 'tickets',
        query: 'text',
        sources: ['tickets'],
        enabled: (term) => shouldSearchTickets(term),
        fetch: async (search, signal, context) => {
            const response = await conversationsTicketsList(
                String(context.currentTeamId),
                { search, limit: SECONDARY_LIMIT },
                { signal }
            )
            return { tickets: response.results.map(ticketToSearchItem) }
        },
    },
    { id: 'persons', query: 'text', sources: ['persons'], fetch: fetchPersons },
    {
        id: 'groups',
        query: 'text',
        sources: ['groups'],
        enabled: (_, context) => context.groupTypes.length > 0,
        fetch: fetchGroups,
    },
]

/** Results for every source of a request, empty where the response held none. */
export const settleSources = (request: RemoteRequest, results: RemoteResults): RemoteResults =>
    Object.fromEntries(request.sources.map((source) => [source, results[source] ?? []]))

export function settleRequest(
    request: RemoteRequest,
    query: string,
    signal: AbortSignal,
    context: RemoteContext,
    deadlineMs = REQUEST_DEADLINE_MS
): Promise<{ results: RemoteResults; failed: boolean } | null> {
    const controller = new AbortController()
    const abort = (): void => controller.abort()
    signal.addEventListener('abort', abort, { once: true })
    const deadline = setTimeout(() => controller.abort(DEADLINE_PASSED), deadlineMs)
    const timedOut = (): boolean => controller.signal.reason === DEADLINE_PASSED
    return (
        request
            .fetch(query, controller.signal, context)
            .then((results) => ({ results: settleSources(request, results), failed: timedOut() }))
            // A failed source settles empty so its section never stays on skeletons.
            .catch((error) =>
                isAbortError(error) && !timedOut() ? null : { results: settleSources(request, {}), failed: true }
            )
            .finally(() => {
                clearTimeout(deadline)
                signal.removeEventListener('abort', abort)
            })
    )
}
