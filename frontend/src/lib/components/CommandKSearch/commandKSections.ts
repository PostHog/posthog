import { SearchItem, filterNewItems } from 'lib/components/Search/searchItems'
import { SETTINGS_THEME_ITEM_ID, filterSearchItems } from 'lib/components/Search/utils'

import { CursorContext, FilterDefinition, FilterOptions, ValueOption, matchValueOptions } from './commandKQuery'
import { buildRankedResults } from './commandKRankedResults'
import { FILTER_TOKEN, freeWords, strictLocalMatches } from './commandKRanking'
import { REMOTE_SOURCES, RESULTS_LIMIT, RemoteSource, SECONDARY_LIMIT } from './commandKSources'

export const RECENTS_LIMIT = 5
export const SUGGESTIONS_LIMIT = 8
export const DEFAULT_SKELETON_ROWS = 3

const TRAILING_SOURCES: RemoteSource[] = ['persons', 'groups']

/** Lists that filter in memory on every keystroke, in the order they render in Search mode. */
const LOCAL_SOURCES = ['products', 'data-management', 'people', 'health', 'misc', 'settings', 'create'] as const
type LocalSource = (typeof LOCAL_SOURCES)[number]

export type CommandKMode = 'empty' | 'key' | 'value' | 'search'

export type CommandKSectionKey =
    | 'filters'
    | 'suggestions'
    | 'recents'
    | 'starred'
    | LocalSource
    | RemoteSource
    | 'ask-ai'
    | 'notice'
    | 'loading-more'
    | 'best-matches'
    | `group-${string}`

export type CommandKRow =
    | { kind: 'filter-key'; key: string; filter: FilterDefinition; negated: boolean }
    | { kind: 'filter-value'; key: string; filter: FilterDefinition; option: ValueOption; negated: boolean }
    | { kind: 'message'; key: string; text: string }
    | { kind: 'skeleton'; key: string }
    | {
          kind: 'item'
          key: string
          item: SearchItem
          section: CommandKSectionKey
          duplicates?: number
          highlightWords?: string[]
          ranked?: boolean
          showCreator?: boolean
          showType?: boolean
      }
    | { kind: 'ask-ai'; key: string; question: string }
    | { kind: 'scope'; key: string; type: string; label: string }
    | { kind: 'notice'; key: string; reason: 'partial' | 'typos'; missing: string[]; shown: string[] }
    | { kind: 'loading-more'; key: string }

export interface CommandKSection {
    key: CommandKSectionKey
    label: string
    rows: CommandKRow[]
    count?: number
    countIsLowerBound?: boolean
    /** `stale` keeps the previous query's rows on screen until the new ones land. */
    state: 'ready' | 'loading' | 'stale'
}

export interface ViewAll {
    item: SearchItem
    placement: 'lead' | 'trail'
}

/** What a remote section can render. Which request is in flight lives elsewhere, so starting one never re-renders. */
export interface RemoteSlot {
    cache: Record<string, SearchItem[]>
    failed?: Record<string, true>
}

export type RemoteSlots = Record<RemoteSource, RemoteSlot>

export const emptyRemoteSlots = (): RemoteSlots =>
    Object.fromEntries(REMOTE_SOURCES.map((source) => [source, { cache: {} }])) as RemoteSlots

const SECTION_LABELS: Record<Exclude<CommandKSectionKey, `group-${string}`>, string> = {
    filters: 'Filters',
    suggestions: 'Suggestions',
    recents: 'Recents',
    starred: 'Starred',
    results: 'Results',
    products: 'Products',
    'data-management': 'Data management',
    people: 'People',
    health: 'Health',
    misc: 'Misc',
    settings: 'Settings',
    create: 'Create new',
    events: 'Events',
    properties: 'Properties',
    workflows: 'Workflows',
    accounts: 'Accounts',
    tickets: 'Support tickets',
    persons: 'Persons',
    groups: 'Groups',
    'ask-ai': 'PostHog AI',
    'best-matches': 'Best matches',
    notice: '',
    'loading-more': '',
}

export const isSelectable = (row: CommandKRow): boolean =>
    row.kind !== 'message' && row.kind !== 'skeleton' && row.kind !== 'notice' && row.kind !== 'loading-more'

const itemIdentity = (item: SearchItem): string => {
    const type = item.record?.type
    const ref = item.record?.ref
    return typeof type === 'string' && typeof ref === 'string' && ref ? `${type}:${ref}` : item.id
}

/**
 * The file system can hold more than one entry for the same object, so a list can repeat an item.
 * Row keys must be unique, because the highlight and the row DOM ids follow the key. Only the first
 * row for each key stays, and the limit applies after that.
 */
const itemRows = (section: CommandKSectionKey, items: SearchItem[], limit = Infinity): CommandKRow[] => {
    const rows: CommandKRow[] = []
    const seen = new Set<string>()
    for (const item of items) {
        if (rows.length >= limit) {
            break
        }
        const key = `${section}/${itemIdentity(item)}`
        if (!seen.has(key)) {
            seen.add(key)
            rows.push({ kind: 'item', key, item, section })
        }
    }
    return rows
}

const readySection = (key: Exclude<CommandKSectionKey, `group-${string}`>, rows: CommandKRow[]): CommandKSection => ({
    key,
    label: SECTION_LABELS[key],
    rows,
    state: 'ready',
})

const skeletonRows = (key: Exclude<CommandKSectionKey, `group-${string}`>): CommandKRow[] =>
    Array.from({ length: DEFAULT_SKELETON_ROWS }, (_, index) => ({ kind: 'skeleton', key: `${key}/skeleton-${index}` }))

const loadingSection = (key: Exclude<CommandKSectionKey, `group-${string}`>): CommandKSection => ({
    ...readySection(key, skeletonRows(key)),
    state: 'loading',
})

const isSettled = (slot: RemoteSlot, query: string | undefined): boolean => !query || query in slot.cache

function remoteSection(
    source: RemoteSource,
    items: SearchItem[],
    state: CommandKSection['state']
): CommandKSection | null {
    const limit = source === 'results' ? RESULTS_LIMIT : SECONDARY_LIMIT
    return items.length > 0 ? { ...readySection(source, itemRows(source, items, limit)), state } : null
}

export interface SuggestionsLoading {
    members: boolean
    folders: boolean
}

/** Value suggestions for the `key:` under the cursor. */
export function buildSuggestions(
    context: Extract<CursorContext, { kind: 'value' }>,
    options: FilterOptions,
    loading: SuggestionsLoading
): CommandKSection {
    const { filter, partial, negated } = context
    const valueRow = (option: ValueOption): CommandKRow => ({
        kind: 'filter-value',
        key: `suggestions/${negated ? '-' : ''}${filter.key}:${option.value}`,
        filter,
        option,
        negated,
    })
    const message = (key: string, text: string): CommandKSection =>
        readySection('suggestions', [{ kind: 'message', key: `suggestions/${key}`, text }])

    if (filter.key === 'name') {
        return partial
            ? readySection('suggestions', [valueRow({ value: partial, label: partial })])
            : message('name-hint', 'Type part of a name')
    }
    if ((filter.key === 'createdBy' && loading.members) || (filter.key === 'in' && loading.folders)) {
        return loadingSection('suggestions')
    }
    const matches = matchValueOptions(options[filter.key], partial, { allowSubstring: filter.key !== 'createdBy' })
    if (matches.length === 0) {
        return filter.key === 'is'
            ? message('no-match', `No type called ${partial}`)
            : message('no-match', `No match for "${partial}". Press Space to search anyway.`)
    }
    // `is:` is a short fixed list, so every type shows. Other keys can have hundreds of values.
    return readySection(
        'suggestions',
        (filter.key === 'is' ? matches : matches.slice(0, SUGGESTIONS_LIMIT)).map(valueRow)
    )
}

export type LocalLists = Record<LocalSource | 'recents' | 'starred', SearchItem[]>

export interface SectionsQuery {
    /** The query each remote source searches for this input. Sources missing here do not apply. */
    remoteQueries: Partial<Record<RemoteSource, string>>
    /** The free text the in-memory lists filter on. Empty while a filter limits the palette to objects. */
    localQuery: string
    /** Leads the Settings section when the query asks about the theme. */
    themeItem: SearchItem | null
    askAiQuestion: string | null
    viewAll: ViewAll | null
}

export interface SectionsInput extends SectionsQuery {
    mode: CommandKMode
    context: CursorContext
    suggestions: CommandKSection | null
    local: LocalLists
    remote: RemoteSlots
    stale: boolean
}

const isRanked = (query: SectionsQuery): boolean =>
    !!query.remoteQueries.results && freeWords(query.remoteQueries.results).length > 0

export function pickDisplayedQuery(
    current: SectionsQuery,
    shown: SectionsQuery | null,
    remote: RemoteSlots
): { query: SectionsQuery; stale: boolean } {
    if (!shown?.remoteQueries.results || isSettled(remote.results, current.remoteQueries.results)) {
        return { query: current, stale: false }
    }
    if (isRanked(current) && !isRanked(shown)) {
        return { query: current, stale: false }
    }
    return { query: shown, stale: true }
}

export const resultsSettled = (query: SectionsQuery, remote: RemoteSlots): boolean =>
    isSettled(remote.results, query.remoteQueries.results)

const filterLocal = (source: LocalSource, items: SearchItem[], query: string): SearchItem[] =>
    source === 'create' ? filterNewItems(items, query) : filterSearchItems(items, query)

function withViewAll(results: CommandKSection | null, viewAll: ViewAll | null): CommandKSection | null {
    if (!viewAll) {
        return results
    }
    const row: CommandKRow = { kind: 'item', key: `results/${viewAll.item.id}`, item: viewAll.item, section: 'results' }
    const rows = results?.rows ?? []
    return {
        ...(results ?? readySection('results', [])),
        rows: viewAll.placement === 'lead' ? [row, ...rows] : [...rows, row],
    }
}

function rankedResultsSections(
    results: SearchItem[],
    query: string,
    local: LocalLists,
    localQuery: string,
    state: CommandKSection['state']
): CommandKSection[] {
    const words = freeWords(query)
    return buildRankedResults({
        query: words.join(' '),
        highlightWords: words,
        results,
        products: localQuery ? local.products : [],
        state,
        scoped: (query.match(FILTER_TOKEN) ?? []).some((token) => token.trim().startsWith('type:')),
    })
}

function lowerSections(input: SectionsInput, ranked: boolean, state: CommandKSection['state']): CommandKSection[] {
    const { local, remote, remoteQueries, localQuery } = input
    const sections: (CommandKSection | null)[] = []
    if (localQuery) {
        for (const source of LOCAL_SOURCES) {
            if (ranked && source === 'products') {
                continue
            }
            const filtered =
                ranked && source !== 'create'
                    ? strictLocalMatches(filterLocal(source, local[source], localQuery), localQuery)
                    : filterLocal(source, local[source], localQuery)
            const themeItem = source === 'settings' ? input.themeItem : null
            const rows = themeItem
                ? itemRows(source, [themeItem, ...filtered], SECONDARY_LIMIT + 1)
                : itemRows(source, filtered, SECONDARY_LIMIT)
            sections.push(rows.length > 0 ? { ...readySection(source, rows), state } : null)
        }
    }
    const loaded = (): CommandKSection[] => sections.filter((section): section is CommandKSection => section !== null)
    const loadingMore = (): CommandKSection[] =>
        state === 'stale'
            ? loaded()
            : [...loaded(), readySection('loading-more', [{ kind: 'loading-more', key: 'loading-more/row' }])]
    const appendInOrder = (sources: RemoteSource[]): boolean => {
        for (const source of sources) {
            const query = remoteQueries[source]
            if (!isSettled(remote[source], query)) {
                return false
            }
            sections.push(query ? remoteSection(source, remote[source].cache[query], state) : null)
        }
        return true
    }
    if (!appendInOrder(REMOTE_SOURCES.filter((source) => source !== 'results' && !TRAILING_SOURCES.includes(source)))) {
        return loadingMore()
    }
    if (input.askAiQuestion) {
        sections.push({
            ...readySection('ask-ai', [{ kind: 'ask-ai', key: 'ask-ai/ask', question: input.askAiQuestion }]),
            state,
        })
    }
    return appendInOrder(TRAILING_SOURCES) ? loaded() : loadingMore()
}

export function buildSections(input: SectionsInput): CommandKSection[] {
    const { mode, context, local, remote, remoteQueries, localQuery } = input
    if (mode === 'empty') {
        return [
            readySection('recents', itemRows('recents', local.recents, RECENTS_LIMIT)),
            readySection('starred', itemRows('starred', local.starred)),
            // Tab rows ("Dashboards / Templates") only appear for a search, as in the current palette.
            readySection(
                'products',
                itemRows(
                    'products',
                    local.products.filter((item) => !item.parentName)
                )
            ),
        ].filter((section) => section.rows.length > 0)
    }

    const state: CommandKSection['state'] = input.stale ? 'stale' : 'ready'
    const sections: (CommandKSection | null)[] = []
    if (context.kind === 'key') {
        sections.push(
            readySection(
                'filters',
                context.matches.map((filter) => ({
                    kind: 'filter-key',
                    key: `filters/${context.negated ? '-' : ''}${filter.key}`,
                    filter,
                    negated: context.negated,
                }))
            )
        )
    }
    sections.push(input.suggestions)
    const resultsQuery = remoteQueries.results
    const results = resultsQuery ? remote.results.cache[resultsQuery] : undefined
    const ranked = isRanked(input)
    if (resultsQuery && !results) {
        sections.push(withViewAll(loadingSection('results'), input.viewAll))
        return sections.filter((section): section is CommandKSection => section !== null)
    }
    if (ranked && results && resultsQuery) {
        const rankedSections = rankedResultsSections(results, resultsQuery, local, localQuery, state)
        sections.push(
            ...(rankedSections.some((section) => section.key === 'results')
                ? rankedSections.map((section) =>
                      section.key === 'results' ? withViewAll(section, input.viewAll) : section
                  )
                : [...rankedSections, withViewAll(null, input.viewAll)])
        )
    } else {
        sections.push(withViewAll(results ? remoteSection('results', results, state) : null, input.viewAll))
    }
    if (mode !== 'value') {
        sections.push(...lowerSections(input, ranked, state))
    }
    return sections.filter((section): section is CommandKSection => section !== null)
}

const THEME_QUERY_WORDS = ['dark', 'light', 'theme', 'appearance']

/**
 * A settings row that switches the theme straight from search. "dark" or "light" sets that mode;
 * "theme" or "appearance" toggles away from the current one.
 */
export function themeSearchItem(
    query: string,
    isDarkModeOn: boolean,
    { setTheme, toggleTheme }: { setTheme: (mode: 'dark' | 'light') => void; toggleTheme: () => void }
): SearchItem | null {
    const normalized = query.trim().toLowerCase()
    if (!normalized || !THEME_QUERY_WORDS.some((word) => normalized.includes(word))) {
        return null
    }
    const requested = normalized.includes('dark') ? 'dark' : normalized.includes('light') ? 'light' : null
    const target = requested ?? (isDarkModeOn ? 'light' : 'dark')
    const name = target === 'dark' ? 'Dark mode' : 'Light mode'
    return {
        id: SETTINGS_THEME_ITEM_ID,
        name,
        displayName: name,
        category: 'settings',
        itemType: 'settings',
        searchKeywords: THEME_QUERY_WORDS,
        onSelect: requested ? () => setTheme(requested) : toggleTheme,
        record: { type: 'settings', ref: 'theme' },
    }
}
