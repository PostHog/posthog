import { SearchItem, filterNewItems } from 'lib/components/Search/searchItems'
import { SETTINGS_THEME_ITEM_ID, filterSearchItems } from 'lib/components/Search/utils'

import { CursorContext, FilterDefinition, FilterOptions, ValueOption, matchValueOptions } from './commandKQuery'
import { REMOTE_SOURCES, RESULTS_LIMIT, RemoteSource, SECONDARY_LIMIT } from './commandKSources'

export const RECENTS_LIMIT = 5
export const SUGGESTIONS_LIMIT = 8
export const DEFAULT_SKELETON_ROWS = 3

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

export type CommandKRow =
    | { kind: 'filter-key'; key: string; filter: FilterDefinition; negated: boolean }
    | { kind: 'filter-value'; key: string; filter: FilterDefinition; option: ValueOption; negated: boolean }
    | { kind: 'message'; key: string; text: string }
    | { kind: 'item'; key: string; item: SearchItem; section: CommandKSectionKey }
    | { kind: 'ask-ai'; key: string; question: string }

export interface CommandKSection {
    key: CommandKSectionKey
    label: string
    rows: CommandKRow[]
    /** `stale` keeps the previous query's rows on screen until the new ones land. */
    state: 'ready' | 'loading' | 'stale'
    skeletonCount: number
}

/** What a remote section can render. Which request is in flight lives elsewhere, so starting one never re-renders. */
export interface RemoteSlot {
    cache: Record<string, SearchItem[]>
    displayedKey: string | null
}

export type RemoteSlots = Record<RemoteSource, RemoteSlot>

export const emptyRemoteSlots = (): RemoteSlots =>
    Object.fromEntries(REMOTE_SOURCES.map((source) => [source, { cache: {}, displayedKey: null }])) as RemoteSlots

const SECTION_LABELS: Record<CommandKSectionKey, string> = {
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
}

export const isSelectable = (row: CommandKRow): boolean => row.kind !== 'message'

const itemIdentity = (item: SearchItem): string => {
    const type = item.record?.type
    const ref = item.record?.ref
    return typeof type === 'string' && typeof ref === 'string' && ref ? `${type}:${ref}` : item.id
}

const itemRows = (section: CommandKSectionKey, items: SearchItem[]): CommandKRow[] =>
    items.map((item) => ({ kind: 'item', key: `${section}/${itemIdentity(item)}`, item, section }))

const readySection = (key: CommandKSectionKey, rows: CommandKRow[]): CommandKSection => ({
    key,
    label: SECTION_LABELS[key],
    rows,
    state: 'ready',
    skeletonCount: 0,
})

const loadingSection = (key: CommandKSectionKey): CommandKSection => ({
    ...readySection(key, []),
    state: 'loading',
    skeletonCount: DEFAULT_SKELETON_ROWS,
})

/**
 * A remote section shows the rows for the current query when they are cached, and the previous
 * query's rows while the new ones load. On its very first load, Results reserves skeleton rows. The
 * other sources usually come back empty, so they reserve nothing rather than flash skeletons that
 * then collapse.
 */
function remoteSection(source: RemoteSource, slot: RemoteSlot, query: string): CommandKSection | null {
    const limit = source === 'results' ? RESULTS_LIMIT : SECONDARY_LIMIT
    const current = slot.cache[query]
    if (current) {
        return current.length > 0 ? readySection(source, itemRows(source, current.slice(0, limit))) : null
    }
    const displayed = slot.displayedKey !== null ? slot.cache[slot.displayedKey] : undefined
    if (displayed) {
        return displayed.length > 0
            ? { ...readySection(source, itemRows(source, displayed.slice(0, limit))), state: 'stale' }
            : null
    }
    return source === 'results' ? loadingSection(source) : null
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

export interface SectionsInput {
    mode: CommandKMode
    context: CursorContext
    suggestions: CommandKSection | null
    local: LocalLists
    remote: RemoteSlots
    /** The query each remote source searches for this input. Sources missing here do not apply. */
    remoteQueries: Partial<Record<RemoteSource, string>>
    /** The free text the in-memory lists filter on. Empty while a filter limits the palette to objects. */
    localQuery: string
    /** Leads the Settings section when the query asks about the theme. */
    themeItem: SearchItem | null
    askAiQuestion: string
}

const filterLocal = (source: LocalSource, items: SearchItem[], query: string): SearchItem[] =>
    (source === 'create' ? filterNewItems(items, query) : filterSearchItems(items, query)).slice(0, SECONDARY_LIMIT)

export function buildSections(input: SectionsInput): CommandKSection[] {
    const { mode, context, local, remote, remoteQueries, localQuery } = input
    if (mode === 'empty') {
        return [
            readySection('recents', itemRows('recents', local.recents.slice(0, RECENTS_LIMIT))),
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

    const remoteSectionFor = (source: RemoteSource): CommandKSection | null => {
        const query = remoteQueries[source]
        return query ? remoteSection(source, remote[source], query) : null
    }
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
    sections.push(input.suggestions, remoteSectionFor('results'))
    if (mode !== 'value' && localQuery) {
        for (const source of LOCAL_SOURCES) {
            const filtered = filterLocal(source, local[source], localQuery)
            const items = source === 'settings' && input.themeItem ? [input.themeItem, ...filtered] : filtered
            sections.push(items.length > 0 ? readySection(source, itemRows(source, items)) : null)
        }
    }
    if (mode !== 'value') {
        sections.push(...REMOTE_SOURCES.filter((source) => source !== 'results').map(remoteSectionFor))
        if (input.askAiQuestion) {
            sections.push(
                readySection('ask-ai', [{ kind: 'ask-ai', key: 'ask-ai/ask', question: input.askAiQuestion }])
            )
        }
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
