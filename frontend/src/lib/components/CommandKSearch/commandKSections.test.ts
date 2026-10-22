import { SearchItem } from 'lib/components/Search/searchItems'

import {
    CommandKMode,
    LocalLists,
    RECENTS_LIMIT,
    SectionsInput,
    ViewAll,
    buildSections,
    emptyRemoteSlots,
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
    ...overrides,
})

const remoteResults = (items: SearchItem[]): Partial<SectionsInput> => {
    const remote = emptyRemoteSlots()
    remote.results = { cache: { 'type:dashboard': items }, displayedKey: 'type:dashboard' }
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
            displayedKey: null,
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
        remote.results = {
            cache: { 'type:dashboard': [{ ...dashboard('a', '1'), rankKey: [] }] },
            displayedKey: 'type:dashboard',
        }
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
        const sections = buildSections(
            input('search', {
                local: { ...emptyLocal(), products: [tab] },
                remoteQueries: { results: 'playlists' },
                localQuery: 'playlists',
            })
        )
        expect(sections[0].rows.map((row) => (row.kind === 'item' ? row.item.name : row.kind))).toEqual(['Collections'])
    })

    it('shows skeletons instead of unranked filter-only rows while ranked results load', () => {
        const remote = emptyRemoteSlots()
        remote.results = { cache: { 'type:dashboard': [dashboard('a', '1')] }, displayedKey: 'type:dashboard' }
        const sections = buildSections(
            input('search', { remote, remoteQueries: { results: 'type:dashboard revenue' }, localQuery: 'revenue' })
        )
        expect(sections.find((section) => section.key === 'results')?.rows.map((row) => row.kind)).toEqual([
            'skeleton',
            'skeleton',
            'skeleton',
        ])
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
            displayedKey: 'type:dashboard xyzzy report',
        }
        const sections = buildSections(
            input('search', { remote, remoteQueries: { results: 'type:dashboard xyzzy report' }, localQuery: '' })
        )
        expect(sections.map((section) => section.key)).toContain('notice')
    })

    it('shows ranked products while saved objects load', () => {
        const sections = buildSections(
            input('search', {
                local: {
                    ...emptyLocal(),
                    products: [{ id: 'product-surveys', name: 'Surveys', category: 'products' }],
                },
                remoteQueries: { results: 'surv' },
                localQuery: 'surv',
            })
        )
        expect(sections.map((section) => [section.key, section.rows.map((row) => row.kind)])).toEqual([
            ['best-matches', ['item']],
            ['results', ['skeleton', 'skeleton', 'skeleton']],
        ])
    })
})
