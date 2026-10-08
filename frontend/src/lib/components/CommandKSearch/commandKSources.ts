import api from 'lib/api'
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
import { uuid } from 'lib/utils/dom'
import { mapGroupQueryResponse } from 'lib/utils/groups'

import type { Noun } from '~/models/groupsModel'
import { GroupType, GroupTypeIndex } from '~/types'

import { conversationsTicketsList } from 'products/conversations/frontend/generated/api'
import { accountsList } from 'products/customer_analytics/frontend/generated/api'
import { personsList } from 'products/persons/frontend/generated/api'

export const RESULTS_LIMIT = 20
export const SECONDARY_LIMIT = 5

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
    signal.throwIfAborted()
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
        fetch: async (search, signal) => {
            const response = await api.fileSystem.list({ search, limit: RESULTS_LIMIT, notType: 'folder', signal })
            return {
                results: response.results.map((entry) =>
                    fileSystemEntryToSearchItem(entry, { id: entry.id, category: 'results' })
                ),
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
