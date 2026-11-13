import { SearchItem, filterNewItems } from 'lib/components/Search/searchItems'
import { SETTINGS_THEME_ITEM_ID, filterSearchItems } from 'lib/components/Search/utils'

import type { SearchCorrection } from './commandKCorrection'
import { CursorContext, FilterDefinition, FilterOptions, ValueOption, matchValueOptions } from './commandKQuery'
import { buildRankedResults } from './commandKRankedResults'
import {
    FILTER_TOKEN,
    MAX_LOCAL_QUERY_LENGTH,
    freeWords,
    searchWords,
    strictLocalMatches,
    tokenTypos,
} from './commandKRanking'
import { REMOTE_SOURCES, RESULTS_LIMIT, RemotePage, RemoteSource, SECONDARY_LIMIT } from './commandKSources'

export const RECENTS_LIMIT = 5
export const SUGGESTIONS_LIMIT = 8
export const DEFAULT_SKELETON_ROWS = 3

const TRAILING_SOURCES: RemoteSource[] = ['persons', 'groups']

/** Lists that filter in memory on every keystroke, in the order they render in Search mode. */
const LOCAL_SOURCES = [
    'products',
    'data-management',
    'people',
    'health',
    'actions',
    'shortcuts',
    'settings',
    'create',
] as const
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
    | { kind: 'expand'; key: string; group: string; label: string }
    | { kind: 'notice'; key: string; reason: 'partial' | 'typos' | 'corrected'; missing: string[]; shown: string[] }
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
    /** Queries the API said match more than it returned, so their section ends with a See all row. */
    more?: Record<string, true>
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
    actions: 'Actions',
    shortcuts: 'Shortcuts',
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

/** The `is:` type a source's See all row scopes the search to. Only sources whose API reports more have one. */
const SEE_ALL_TYPES: Partial<Record<RemoteSource, string>> = { persons: 'person' }

function remoteSection(
    source: RemoteSource,
    { items, more }: RemotePage,
    state: CommandKSection['state']
): CommandKSection | null {
    const limit = source === 'results' ? RESULTS_LIMIT : SECONDARY_LIMIT
    const type = SEE_ALL_TYPES[source]
    const seeAll: CommandKRow[] =
        more && type
            ? [
                  {
                      kind: 'scope',
                      key: `${source}/see-all`,
                      type,
                      label: `See all ${SECTION_LABELS[source].toLowerCase()}`,
                  },
              ]
            : []
    // When ranking moves every item into Results, the section keeps only its See all row.
    const rows = [...itemRows(source, items, limit), ...seeAll]
    return rows.length > 0 ? { ...readySection(source, rows), state } : null
}

/** A cached query's page, as the request returned it. */
export const cachedPage = (slot: RemoteSlot, query: string): RemotePage =>
    slot.more?.[query] ? { items: slot.cache[query], more: true } : { items: slot.cache[query] }

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
    personsFirst: boolean
    searchCorrection: SearchCorrection | null
    expandedGroups?: string[]
}

const isRanked = (query: SectionsQuery): boolean =>
    !!query.remoteQueries.results && freeWords(query.remoteQueries.results).length > 0

export const resultsSettled = (query: SectionsQuery, remote: RemoteSlots): boolean =>
    isSettled(remote.results, query.remoteQueries.results) &&
    (!isRanked(query) || isSettled(remote.accounts, query.remoteQueries.accounts))

export function pickDisplayedQuery(
    current: SectionsQuery,
    shown: SectionsQuery | null,
    remote: RemoteSlots
): { query: SectionsQuery; stale: boolean } {
    if (!shown?.remoteQueries.results || resultsSettled(current, remote)) {
        return { query: current, stale: false }
    }
    if (isRanked(current) && !isRanked(shown)) {
        return { query: current, stale: false }
    }
    return { query: shown, stale: true }
}

const exactSettingsMatches = (settings: SearchItem[], localQuery: string): SearchItem[] =>
    localQuery ? matchLocal('settings', settings, localQuery, true) : []

const matchesWord = (words: string[]) => (token: string) => words.some((word) => tokenTypos(token, word) === 0)

function settingsMatches(items: SearchItem[], fullQuery: string): SearchItem[] {
    const query = fullQuery.trim().replace(/\s+/g, ' ').slice(0, MAX_LOCAL_QUERY_LENGTH)
    const tokens = searchWords(query)
    if (!tokens.length) {
        return []
    }
    const byNameOrAlias = strictLocalMatches(items, query)
    const named = new Set(byNameOrAlias.map((item) => item.id))
    const acrossFields = items.filter((item) => {
        if (named.has(item.id)) {
            return false
        }
        const own = matchesWord(
            [String(item.displayName || item.name), ...(item.searchKeywords ?? [])].flatMap(searchWords)
        )
        const context = matchesWord([item.parentName ?? '', ...(item.contextKeywords ?? [])].flatMap(searchWords))
        return tokens.some(own) && tokens.every((token) => own(token) || context(token))
    })
    return [...byNameOrAlias, ...acrossFields]
}

const LOCAL_MATCH_CACHE_SIZE = 50
const localMatchCache = new WeakMap<SearchItem[], Map<string, SearchItem[]>>()

function matchLocal(source: LocalSource, items: SearchItem[], query: string, ranked: boolean): SearchItem[] {
    const strict = ranked && source !== 'create'
    const key = `${strict ? 'strict' : 'fuzzy'}:${query}`
    let byQuery = localMatchCache.get(items)
    if (!byQuery) {
        byQuery = new Map()
        localMatchCache.set(items, byQuery)
    }
    const cached = byQuery.get(key)
    if (cached) {
        return cached
    }
    const matches =
        strict && source === 'settings'
            ? settingsMatches(items, query)
            : strict
              ? strictLocalMatches(items, query)
              : source === 'create'
                ? filterNewItems(items, query)
                : filterSearchItems(items, query)
    if (byQuery.size >= LOCAL_MATCH_CACHE_SIZE) {
        byQuery.delete(byQuery.keys().next().value!)
    }
    byQuery.set(key, matches)
    return matches
}

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

const plainName = (item: SearchItem): string =>
    String(item.displayName || item.name)
        .toLowerCase()
        .replace(/\s*\([^)]*\)\s*$/, '')
        .trim()

export function rankableSettings(local: LocalLists, localQuery: string): SearchItem[] {
    const productDestinations = new Set(
        local.products.filter((item) => !item.parentName).map((item) => `${plainName(item)}|${item.href ?? ''}`)
    )
    return exactSettingsMatches(local.settings, localQuery).filter(
        (item) => !productDestinations.has(`${plainName(item)}|${item.href ?? ''}`)
    )
}

function rankedResultsSections(
    results: SearchItem[],
    query: string,
    local: LocalLists,
    localQuery: string,
    state: CommandKSection['state'],
    persons: SearchItem[],
    accounts: SearchItem[],
    themeItem: SearchItem | null,
    expandedGroups: string[]
): CommandKSection[] {
    const words = freeWords(query)
    // The scorer splits words on underscores, so the settings it ranks are matched the same way.
    const rankedSettingsQuery = localQuery.replace(/_/g, ' ')
    const rankable = rankableSettings(local, rankedSettingsQuery)
    // The scorer reads punctuation, so a domain or an email address keeps it.
    const freeText = query.replace(FILTER_TOKEN, ' ').replace(/\s+/g, ' ').trim()
    return buildRankedResults({
        persons,
        accounts,
        settings: [...(themeItem ? [themeItem] : []), ...rankable],
        unrankedSettings: exactSettingsMatches(local.settings, rankedSettingsQuery).filter(
            (item) => !rankable.some((ranked) => ranked.id === item.id)
        ),
        expandedGroups,
        query: freeText,
        highlightWords: words,
        results,
        products: localQuery ? local.products : [],
        state,
        scoped: (query.match(FILTER_TOKEN) ?? []).some((token) => token.trim().startsWith('type:')),
    })
}

interface LowerSectionsContext {
    ranked: boolean
    state: CommandKSection['state']
    /** Item IDs already shown above, so no item repeats. */
    shown: Set<string>
    settingsRanked: boolean
    /** Section keys already placed above. Persons lead an email search, and then own their section there. */
    placedAbove: Set<string>
}

function lowerSections(
    input: SectionsInput,
    { ranked, state, shown, settingsRanked, placedAbove }: LowerSectionsContext
): CommandKSection[] {
    const { local, remote, remoteQueries, localQuery } = input
    const sections: (CommandKSection | null)[] = []
    const loaded = (): CommandKSection[] => sections.filter((section): section is CommandKSection => section !== null)
    const loadingMore = (): CommandKSection[] =>
        state === 'stale'
            ? loaded()
            : [...loaded(), readySection('loading-more', [{ kind: 'loading-more', key: 'loading-more/row' }])]
    const appendInOrder = (sources: RemoteSource[]): boolean => {
        for (const source of sources.filter((source) => !placedAbove.has(source))) {
            const query = remoteQueries[source]
            if (!isSettled(remote[source], query)) {
                return false
            }
            sections.push(
                query
                    ? remoteSection(
                          source,
                          {
                              ...cachedPage(remote[source], query),
                              items: remote[source].cache[query].filter((item) => !shown.has(item.id)),
                          },
                          state
                      )
                    : null
            )
        }
        return true
    }
    if (localQuery) {
        for (const source of LOCAL_SOURCES) {
            const themeItem =
                source === 'settings' && input.themeItem && !shown.has(input.themeItem.id) ? input.themeItem : null
            if (ranked && (source === 'products' || (source === 'settings' && settingsRanked && !themeItem))) {
                continue
            }
            const filtered =
                ranked && source === 'settings' && settingsRanked
                    ? []
                    : matchLocal(source, local[source], localQuery, ranked).filter((item) => !shown.has(item.id))
            const rows = themeItem
                ? itemRows(source, [themeItem, ...filtered], SECONDARY_LIMIT + 1)
                : itemRows(source, filtered, SECONDARY_LIMIT)
            sections.push(rows.length > 0 ? { ...readySection(source, rows), state } : null)
        }
    }
    if (!appendInOrder(REMOTE_SOURCES.filter((source) => source !== 'results' && !TRAILING_SOURCES.includes(source)))) {
        return loadingMore()
    }
    const hasItems = shown.size > 0 || loaded().some((section) => section.rows.some((row) => row.kind === 'item'))
    if (input.askAiQuestion && !hasItems) {
        sections.push({
            ...readySection('ask-ai', [{ kind: 'ask-ai', key: 'ask-ai/ask', question: input.askAiQuestion }]),
            state,
        })
    }
    if (!appendInOrder(TRAILING_SOURCES)) {
        return loadingMore()
    }
    const all = loaded()
    return all.some((section) => section.key !== 'ask-ai' && section.rows.some((row) => row.kind === 'item'))
        ? all.filter((section) => section.key !== 'ask-ai')
        : all
}

function withCorrectionNotice(sections: CommandKSection[], correction: SearchCorrection | null): CommandKSection[] {
    if (!correction || !sections.some((section) => section.rows.some((row) => row.kind === 'item'))) {
        return sections
    }
    const row: CommandKRow = {
        kind: 'notice',
        key: 'notice/corrected',
        reason: 'corrected',
        missing: [correction.from],
        shown: [correction.to],
    }
    const notice = sections.find((section) => section.key === 'notice')
    if (notice) {
        return sections.map((section) => (section === notice ? { ...section, rows: [row, ...section.rows] } : section))
    }
    const index = sections.findIndex((section) => section.key !== 'filters' && section.key !== 'suggestions')
    const at = index < 0 ? sections.length : index
    return [...sections.slice(0, at), readySection('notice', [row]), ...sections.slice(at)]
}

export function buildSections(input: SectionsInput): CommandKSection[] {
    return withCorrectionNotice(buildSectionsForQuery(input), input.searchCorrection)
}

function buildSectionsForQuery(input: SectionsInput): CommandKSection[] {
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
            readySection('shortcuts', itemRows('shortcuts', local.shortcuts)),
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
    const personsQuery = input.personsFirst && mode !== 'value' ? remoteQueries.persons : undefined
    const accountsQuery = ranked && mode !== 'value' ? remoteQueries.accounts : undefined
    if (
        (resultsQuery && !results) ||
        (personsQuery && !isSettled(remote.persons, personsQuery)) ||
        (accountsQuery && !isSettled(remote.accounts, accountsQuery))
    ) {
        sections.push(withViewAll(loadingSection('results'), input.viewAll))
        return sections.filter((section): section is CommandKSection => section !== null)
    }
    const leadingPersons = personsQuery ? remote.persons.cache[personsQuery] : []
    if (!ranked && personsQuery && leadingPersons.length) {
        sections.push(remoteSection('persons', cachedPage(remote.persons, personsQuery), state))
    }
    if (ranked && results && resultsQuery) {
        const rankedSections = rankedResultsSections(
            results,
            resultsQuery,
            local,
            localQuery,
            state,
            leadingPersons,
            accountsQuery ? remote.accounts.cache[accountsQuery] : [],
            input.themeItem,
            input.expandedGroups ?? []
        )
        sections.push(
            ...(rankedSections.some((section) => section.key === 'results')
                ? rankedSections.map((section) =>
                      section.key === 'results' ? withViewAll(section, input.viewAll) : section
                  )
                : [...rankedSections, withViewAll(null, input.viewAll)])
        )
    } else {
        sections.push(withViewAll(results ? remoteSection('results', { items: results }, state) : null, input.viewAll))
    }
    if (mode !== 'value') {
        const themeItem = input.themeItem
        const settingsGroupIndex = sections.findIndex((section) => section?.key === 'group-settings')
        const settingsGroup = sections[settingsGroupIndex]
        if (
            ranked &&
            themeItem &&
            settingsGroup &&
            !sections.some((section) =>
                section?.rows.some((row) => row.kind === 'item' && row.item.id === themeItem.id)
            )
        ) {
            sections[settingsGroupIndex] = {
                ...settingsGroup,
                rows: [
                    {
                        kind: 'item',
                        key: `group-settings/${themeItem.id}`,
                        item: themeItem,
                        section: 'settings',
                        ranked: true,
                        highlightWords: freeWords(localQuery),
                    },
                    ...settingsGroup.rows,
                ],
            }
        }
        const shown = new Set(
            sections.flatMap(
                (section) => section?.rows.flatMap((row) => (row.kind === 'item' ? [row.item.id] : [])) ?? []
            )
        )
        const settingsRanked = sections.some(
            (section) => section?.rows.some((row) => row.kind === 'item' && row.item.category === 'settings') ?? false
        )
        const placedAbove = new Set(sections.flatMap((section) => (section ? [section.key] : [])))
        sections.push(...lowerSections(input, { ranked, state, shown, settingsRanked, placedAbove }))
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
