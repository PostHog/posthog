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
    remote.results = { cache: { revenue: items }, displayedKey: 'revenue' }
    return { remote, remoteQueries: { results: 'revenue' } }
}

const product = (name: string, extra: Partial<SearchItem> = {}): SearchItem => ({
    id: name,
    name,
    category: 'tools',
    ...extra,
})

describe('buildSections', () => {
    test.each<[string, string, Record<string, string[]>]>([
        [
            'pins name matches above results, exact match first, but never a tab row',
            'logs',
            { 'top-match': ['Logs', 'Logs explorer'], results: ['Dashboard 1'], products: ['Logs live tail'] },
        ],
        ['never pins a keyword-only match', 'observability', { results: ['Dashboard 1'], products: ['Logs'] }],
    ])('%s', (_, localQuery, expected) => {
        const local = {
            ...emptyLocal(),
            products: [
                product('Logs explorer'),
                product('Logs', { searchKeywords: ['observability'] }),
                product('Logs live tail', { category: 'tabs', parentName: 'Logs explorer' }),
            ],
        }
        const remote = emptyRemoteSlots()
        remote.results = { cache: { [localQuery]: [dashboard('entry', '1')] }, displayedKey: localQuery }
        const sections = buildSections(
            input('search', { local, localQuery, remote, remoteQueries: { results: localQuery } })
        )
        const names = Object.fromEntries(
            sections.map((section) => [
                section.key,
                section.rows.map((row) => (row.kind === 'item' ? row.item.name : row.key)),
            ])
        )
        expect(names).toEqual(expected)
    })

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
        const loading = buildSections(input('search', { remoteQueries: { results: 'x' }, viewAll }))
        const loaded = buildSections(input('search', { ...remoteResults([dashboard('a', '1')]), viewAll }))
        const rowKeys = (sections: ReturnType<typeof buildSections>): string[] =>
            sections.find((section) => section.key === 'results')?.rows.map((row) => row.key.replace('results/', '')) ??
            []
        expect(rowKeys(loading)).toEqual(whileLoading)
        expect(rowKeys(loaded)).toEqual(onceLoaded)
    })
})
