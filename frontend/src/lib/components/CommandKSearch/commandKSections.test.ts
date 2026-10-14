import { SearchItem } from 'lib/components/Search/searchItems'

import {
    CommandKMode,
    LocalLists,
    RECENTS_LIMIT,
    SectionsInput,
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
    askAiQuestion: '',
    ...overrides,
})

const remoteResults = (items: SearchItem[]): Partial<SectionsInput> => {
    const remote = emptyRemoteSlots()
    remote.results = { cache: { revenue: items }, displayedKey: 'revenue' }
    return { remote, remoteQueries: { results: 'revenue' } }
}

const page = (name: string, category: string, searchKeywords?: string[]): SearchItem => ({
    id: name,
    name,
    category,
    searchKeywords,
})

const localWithModels = (): LocalLists => ({
    ...emptyLocal(),
    products: [
        page('Playground', 'tools', ['model comparison']),
        page('MCP analytics', 'tools', ['model context protocol']),
    ],
    'data-management': [page('Models', 'data-management')],
})

describe('buildSections', () => {
    test.each<[string, string, Record<string, string[]>]>([
        [
            'drops keyword-only rows when another section has an exact name match',
            'models',
            { 'data-management': ['Models'] },
        ],
        [
            'drops keyword-only rows when another section has a prefix name match',
            'mod',
            { 'data-management': ['Models'] },
        ],
        ['keeps keyword-only rows when no section matches by name', 'model comparison', { products: ['Playground'] }],
    ])('%s', (_, localQuery, expected) => {
        const sections = buildSections(input('search', { local: localWithModels(), localQuery }))
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
})
