import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { signalsScoutScratchpadSearch } from 'products/signals/frontend/generated/api'
import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import type { scratchpadLogicType } from './scratchpadLogicType'

// The list view shows two ways to read the fleet's memory: newest-first (the API's
// native order) or clustered by the key namespace scouts choose (`tags:*`, `dedupe:*`).
export type ScratchpadGrouping = 'recent' | 'topic'

// Search reruns the server-side ILIKE on every keystroke; debounce so typing doesn't
// fire a request per character.
const SEARCH_DEBOUNCE_MS = 300
// `list` caps at 500 newest-first with no pagination wrapper — pull the whole window in
// one read and group/search client-side. The endpoint exposes a `date_to` cursor for
// walking past the cap; a team that routinely exceeds 500 wants that wired into a "load
// more" here, not a bigger single read.
const SCRATCHPAD_FETCH_LIMIT = 500

/** One namespace cluster in the "By topic" view: the raw prefix, a friendly label, and its entries. */
export interface ScratchpadNamespaceGroup {
    namespace: string
    label: string
    entries: ScratchpadEntryApi[]
}

/** Scouts namespace keys with a leading `prefix:` (e.g. `tags:errors:taxonomy`). Everything
 * before the first colon is the topic; keys without one fall into a shared "General" bucket. */
export function scratchpadNamespaceOf(key: string): string {
    const idx = key.indexOf(':')
    return idx > 0 ? key.slice(0, idx) : 'general'
}

export function humanizeNamespace(namespace: string): string {
    if (namespace === 'general') {
        return 'General'
    }
    return namespace.replace(/[-_]/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

/**
 * Read-only view over the scout fleet's durable memory (`SignalScratchpad`). Owns the entry list,
 * the debounced search text (wired straight to the endpoint's `?text=` ILIKE), and the recent /
 * by-topic grouping toggle. There is no write surface on purpose — humans inspect this memory;
 * only the harness (internal-scope) writes it.
 */
export const scratchpadLogic = kea<scratchpadLogicType>([
    path(['scenes', 'inbox', 'logics', 'scratchpadLogic']),

    actions({
        setSearchText: (searchText: string) => ({ searchText }),
        setGrouping: (grouping: ScratchpadGrouping) => ({ grouping }),
        toggleNamespace: (namespace: string) => ({ namespace }),
    }),

    loaders(({ values }) => ({
        entries: [
            null as ScratchpadEntryApi[] | null,
            {
                loadEntries: async (_payload: void, breakpoint) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const text = values.searchText.trim()
                    const results = await signalsScoutScratchpadSearch(String(teamId), {
                        text: text || undefined,
                        limit: SCRATCHPAD_FETCH_LIMIT,
                    })
                    // Drop a stale response if the search moved on while this request was in flight.
                    breakpoint()
                    return results
                },
            },
        ],
    })),

    reducers({
        searchText: ['', { setSearchText: (_, { searchText }) => searchText }],
        grouping: ['recent' as ScratchpadGrouping, { setGrouping: (_, { grouping }) => grouping }],
        // Did the most recent load reject? Lets the panel tell a failed load apart from an empty
        // project (kea-loaders leaves `entries` at its prior value on failure, so it can't).
        loadFailed: [
            false,
            {
                loadEntries: () => false,
                loadEntriesSuccess: () => false,
                loadEntriesFailure: () => true,
            },
        ],
        // Which "By topic" clusters are open. Start collapsed (high-level view of topics first);
        // switching grouping resets the set so entering "By topic" always opens fully collapsed.
        expandedNamespaces: [
            [] as string[],
            {
                toggleNamespace: (state, { namespace }) =>
                    state.includes(namespace) ? state.filter((n) => n !== namespace) : [...state, namespace],
                setGrouping: () => [],
            },
        ],
    }),

    selectors({
        totalCount: [(s) => [s.entries], (entries): number | null => (entries ? entries.length : null)],
        // Entries are newest-first, so the head's timestamp drives the callout's "updated when" hint.
        lastUpdatedAt: [(s) => [s.entries], (entries): string | null => entries?.[0]?.updated_at ?? null],
        // Entries arrive newest-first; preserve that order within each namespace cluster, and order
        // the clusters by their most recently touched entry so the liveliest topic floats to the top.
        groups: [
            (s) => [s.entries],
            (entries): ScratchpadNamespaceGroup[] => {
                const byNamespace = new Map<string, ScratchpadEntryApi[]>()
                for (const entry of entries ?? []) {
                    const namespace = scratchpadNamespaceOf(entry.key)
                    const bucket = byNamespace.get(namespace)
                    if (bucket) {
                        bucket.push(entry)
                    } else {
                        byNamespace.set(namespace, [entry])
                    }
                }
                return [...byNamespace.entries()]
                    .map(([namespace, namespaceEntries]) => ({
                        namespace,
                        label: humanizeNamespace(namespace),
                        entries: namespaceEntries,
                    }))
                    .sort((a, b) => (b.entries[0]?.updated_at ?? '').localeCompare(a.entries[0]?.updated_at ?? ''))
            },
        ],
    }),

    listeners(({ actions }) => ({
        setSearchText: async (_, breakpoint) => {
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.loadEntries()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadEntries()
    }),
])
