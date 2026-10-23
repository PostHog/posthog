import { SearchItem } from 'lib/components/Search/searchItems'

import {
    CommandKMode,
    LocalLists,
    RECENTS_LIMIT,
    SectionsInput,
    SectionsQuery,
    ViewAll,
    buildSections,
    emptyRemoteSlots,
    pickDisplayedQuery,
} from './commandKSections'
import { RESULTS_LIMIT } from './commandKSources'

const dashboard = (id: string, ref: string): SearchItem => ({
    id,
    name: `Dashboard ${ref}`,
    category: 'results',
    record: { type: 'dashboard', ref },
})

// Two file system entries point at dashboard 1, so its rows share a key.
const itemsWithRepeats = (count: number): SearchItem[] => [
    dashboard('entry-a', '1'),
    dashboard('entry-b', '1'),
    ...Array.from({ length: count }, (_, index) => dashboard(`entry-${index}`, String(index + 2))),
]

const emptyLocal = (): LocalLists => ({
    products: [],
    'data-management': [],
    people: [],
    health: [],
    misc: [],
    settings: [],
    create: [],
    recents: [],
    starred: [],
})

const input = (mode: CommandKMode, overrides: Partial<SectionsInput>): SectionsInput => ({
    mode,
    context: mode === 'empty' ? { kind: 'empty' } : { kind: 'text', token: null },
    suggestions: null,
    local: emptyLocal(),
    remote: emptyRemoteSlots(),
    remoteQueries: {},
    localQuery: '',
    themeItem: null,
    askAiQuestion: null,
    viewAll: null,
    stale: false,
    ...overrides,
})

const query = (overrides: Partial<SectionsQuery>): SectionsQuery => ({
    remoteQueries: {},
    localQuery: '',
    themeItem: null,
    askAiQuestion: null,
    viewAll: null,
    ...overrides,
})

const sectionKinds = (sections: ReturnType<typeof buildSections>): [string, string[]][] =>
    sections.map((section) => [section.key, section.rows.map((row) => row.kind)])

const remoteResults = (items: SearchItem[]): Partial<SectionsInput> => {
    const remote = emptyRemoteSlots()
    remote.results = { cache: { 'type:dashboard': items } }
    return { remote, remoteQueries: { results: 'type:dashboard' } }
}

describe('buildSections', () => {
    test.each<[string, SectionsInput, string, number]>([
        ['remote results', input('search', remoteResults(itemsWithRepeats(RESULTS_LIMIT))), 'results', RESULTS_LIMIT],
        [
            'recents',
            input('empty', { local: { ...emptyLocal(), recents: itemsWithRepeats(RECENTS_LIMIT) } }),
            'recents',
            RECENTS_LIMIT,
        ],
    ])('shows an item once in %s, then fills up to the limit', (_, sectionsInput, sectionKey, limit) => {
        const section = buildSections(sectionsInput).find((candidate) => candidate.key === sectionKey)
        const keys = section?.rows.map((row) => row.key) ?? []
        expect(keys).toHaveLength(limit)
        expect(new Set(keys).size).toBe(limit)
        expect(keys[0]).toBe(`${sectionKey}/dashboard:1`)
    })

    test.each([
        ['lead', ['view-all', 'skeleton-0', 'skeleton-1', 'skeleton-2'], ['view-all', 'dashboard:1']],
        ['trail', ['skeleton-0', 'skeleton-1', 'skeleton-2', 'view-all'], ['dashboard:1', 'view-all']],
    ] as const)('places a %s View all row before and after results load', (placement, whileLoading, onceLoaded) => {
        const viewAll: ViewAll = {
            item: { id: 'view-all', name: 'View all feature flags', category: 'results', href: '/feature_flags' },
            placement,
        }
        const loading = buildSections(input('search', { remoteQueries: { results: 'type:dashboard' }, viewAll }))
        const loaded = buildSections(input('search', { ...remoteResults([dashboard('a', '1')]), viewAll }))
        const rowKeys = (sections: ReturnType<typeof buildSections>): string[] =>
            sections.find((section) => section.key === 'results')?.rows.map((row) => row.key.replace('results/', '')) ??
            []
        expect(rowKeys(loading)).toEqual(whileLoading)
        expect(rowKeys(loaded)).toEqual(onceLoaded)
    })

    it('keeps the View all row on ranked results of one type', () => {
        const viewAll: ViewAll = {
            item: { id: 'view-all', name: 'View all dashboards', category: 'results', href: '/dashboard' },
            placement: 'trail',
        }
        const remote = emptyRemoteSlots()
        remote.results = {
            cache: { 'type:dashboard revenue': [{ ...dashboard('a', '1'), rankKey: [-1, 0, 0, 0, -1, 0, 2, 0, 0] }] },
        }
        const sections = buildSections(
            input('search', {
                remote,
                remoteQueries: { results: 'type:dashboard revenue' },
                localQuery: 'revenue',
                viewAll,
            })
        )
        expect(sections.find((section) => section.key === 'results')?.rows.map((row) => row.key)).toEqual([
            'results/a',
            'results/view-all',
        ])
    })

    it('lists filter-only results without ranking them', () => {
        const remote = emptyRemoteSlots()
        remote.results = { cache: { 'type:dashboard': [{ ...dashboard('a', '1'), rankKey: [] }] } }
        const sections = buildSections(input('search', { remote, remoteQueries: { results: 'type:dashboard' } }))
        expect(sections.find((section) => section.key === 'results')?.rows.map((row) => row.key)).toEqual([
            'results/dashboard:1',
        ])
    })

    it('ranks product tabs with the products', () => {
        const tab: SearchItem = {
            id: 'product-collections',
            name: 'Collections',
            category: 'products',
            parentName: 'Session replay',
            searchKeywords: ['playlists'],
        }
        const remote = emptyRemoteSlots()
        remote.results = { cache: { playlists: [] } }
        const sections = buildSections(
            input('search', {
                local: { ...emptyLocal(), products: [tab] },
                remote,
                remoteQueries: { results: 'playlists' },
                localQuery: 'playlists',
            })
        )
        expect(sections[0].rows.map((row) => (row.kind === 'item' ? row.item.name : row.kind))).toEqual(['Collections'])
    })

    it('shows skeletons instead of unranked filter-only rows while ranked results load', () => {
        const remote = emptyRemoteSlots()
        remote.results = { cache: { 'type:dashboard': [dashboard('a', '1')] } }
        const current = query({ remoteQueries: { results: 'type:dashboard revenue' }, localQuery: 'revenue' })
        const shown = query({ remoteQueries: { results: 'type:dashboard' } })

        expect(pickDisplayedQuery(current, shown, remote)).toEqual({ query: current, stale: false })
    })

    it('shows the current query loading when the last loaded one had nothing to search', () => {
        const current = query({ remoteQueries: { results: 'type:dashboard' } })

        expect(pickDisplayedQuery(current, query({}), emptyRemoteSlots())).toEqual({ query: current, stale: false })
    })

    it('keeps the last loaded query on screen until the current one loads', () => {
        const remote = emptyRemoteSlots()
        remote.results = { cache: { rev: [dashboard('a', '1')] } }
        const shown = query({ remoteQueries: { results: 'rev' }, localQuery: 'rev' })
        const current = query({ remoteQueries: { results: 'reve' }, localQuery: 'reve' })

        expect(pickDisplayedQuery(current, shown, remote)).toEqual({ query: shown, stale: true })

        remote.results = { cache: { ...remote.results.cache, reve: [] } }
        expect(pickDisplayedQuery(current, shown, remote)).toEqual({ query: current, stale: false })
    })

    test.each<[string, Partial<Record<'events' | 'persons', SearchItem[]>>, string[]]>([
        [
            'only a loading row below Results while an earlier source loads',
            { persons: [dashboard('p', '9')] },
            ['results', 'loading-more'],
        ],
        [
            'PostHog AI without waiting for slow person searches',
            { events: [dashboard('e', '8')] },
            ['results', 'events', 'ask-ai', 'loading-more'],
        ],
        [
            'persons last, below PostHog AI, once they load',
            { events: [dashboard('e', '8')], persons: [dashboard('p', '9')] },
            ['results', 'events', 'ask-ai', 'persons'],
        ],
    ])('reveals %s', (_, loaded, expectedKeys) => {
        const remote = emptyRemoteSlots()
        remote.results = { cache: { 'type:dashboard': [dashboard('a', '1')] } }
        for (const [source, items] of Object.entries(loaded)) {
            remote[source as 'events' | 'persons'] = { cache: { rev: items } }
        }
        const sections = buildSections(
            input('search', {
                remote,
                remoteQueries: { results: 'type:dashboard', events: 'rev', persons: 'rev' },
                askAiQuestion: 'rev',
            })
        )
        expect(sections.map((section) => section.key)).toEqual(expectedKeys)
    })

    it('says which words were dropped when a filter is active', () => {
        const remote = emptyRemoteSlots()
        remote.results = {
            cache: {
                'type:dashboard xyzzy report': [
                    {
                        ...dashboard('a', '1'),
                        rankKey: [-1, 0, 0, 1, -1, 1, 5, 0, -1],
                        searchMatch: {
                            matchedAllWords: false,
                            matchedWords: ['report'],
                            typeCount: 1,
                            countsCapped: false,
                            withTypos: false,
                        },
                    },
                ],
            },
        }
        const sections = buildSections(
            input('search', { remote, remoteQueries: { results: 'type:dashboard xyzzy report' }, localQuery: '' })
        )
        expect(sections.map((section) => section.key)).toContain('notice')
    })

    it('holds ranked products back until saved objects load, so they never reorder', () => {
        const local = { ...emptyLocal(), products: [{ id: 'product-surveys', name: 'Surveys', category: 'products' }] }
        const loading = input('search', { local, remoteQueries: { results: 'surv' }, localQuery: 'surv' })
        const remote = emptyRemoteSlots()
        remote.results = { cache: { surv: [] } }

        expect(sectionKinds(buildSections(loading))).toEqual([['results', ['skeleton', 'skeleton', 'skeleton']]])
        expect(sectionKinds(buildSections({ ...loading, remote }))).toEqual([['best-matches', ['item']]])
    })
})
