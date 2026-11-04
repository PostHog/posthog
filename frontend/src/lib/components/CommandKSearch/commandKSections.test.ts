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
    resultsSettled,
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
    actions: [],
    shortcuts: [],
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
    personsFirst: false,
    unifiedRanking: false,
    searchCorrection: null,
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
    it('shows every shortcut last when the input is empty', () => {
        const shortcuts = [dashboard('shortcut-1', '1'), dashboard('shortcut-2', '2')]
        const sections = buildSections(input('empty', { local: { ...emptyLocal(), shortcuts } }))

        expect(sections.at(-1)?.key).toBe('shortcuts')
        expect(sections.at(-1)?.rows).toHaveLength(2)
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
        const loading = buildSections(input('search', { remoteQueries: { results: 'type:dashboard' }, viewAll }))
        const loaded = buildSections(input('search', { ...remoteResults([dashboard('a', '1')]), viewAll }))
        const rowKeys = (sections: ReturnType<typeof buildSections>): string[] =>
            sections.find((section) => section.key === 'results')?.rows.map((row) => row.key.replace('results/', '')) ??
            []
        expect(rowKeys(loading)).toEqual(whileLoading)
        expect(rowKeys(loaded)).toEqual(onceLoaded)
    })

    const alerts: SearchItem[] = [
        { id: 'alert-2', name: 'Revenue drop', category: 'results', record: { type: 'alert', id: '2' } },
        { id: 'alert-1', name: 'Weekly revenue', category: 'results', record: { type: 'alert', id: '1' } },
    ]
    const ticketMatchedInMessage: SearchItem = {
        id: 'ticket-1',
        name: 'Card declined',
        category: 'results',
        record: { type: 'ticket', id: '1' },
    }
    test.each<[string, string, SearchItem[], string[], boolean]>([
        [
            'file system results with a server rank',
            'type:dashboard revenue',
            [{ ...dashboard('a', '1'), rankKey: [-1, 0, 0, 0, -1, 0, 2, 0, 0] }],
            ['results/a'],
            false,
        ],
        [
            'results from a type API that sends no rank, in the order it sent them',
            'type:alert revenue',
            alerts,
            ['results/alert-2', 'results/alert-1'],
            false,
        ],
        [
            'a type API result that matched outside its name, with unified ranking',
            'type:ticket revenue',
            [ticketMatchedInMessage],
            ['results/ticket-1'],
            true,
        ],
    ])('keeps the View all row after ranked %s', (_, results, items, rowKeys, unifiedRanking) => {
        const viewAll: ViewAll = {
            item: { id: 'view-all', name: 'View all', category: 'results', href: '/list' },
            placement: 'trail',
        }
        const remote = emptyRemoteSlots()
        remote.results = { cache: { [results]: items } }
        const sections = buildSections(
            input('search', { remote, remoteQueries: { results }, localQuery: 'revenue', viewAll, unifiedRanking })
        )
        expect(sections.find((section) => section.key === 'results')?.rows.map((row) => row.key)).toEqual([
            ...rowKeys,
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

    test.each<[string, Partial<Record<'events' | 'persons', SearchItem[]>>, boolean, string[]]>([
        [
            'only a loading row below Results while an earlier source loads',
            { persons: [dashboard('p', '9')] },
            false,
            ['results', 'loading-more'],
        ],
        [
            'no PostHog AI row while other rows match',
            { events: [dashboard('e', '8')] },
            false,
            ['results', 'events', 'loading-more'],
        ],
        [
            'persons last, once they load',
            { events: [dashboard('e', '8')], persons: [dashboard('p', '9')] },
            false,
            ['results', 'events', 'persons'],
        ],
        [
            'only result skeletons while persons that go first load',
            { events: [dashboard('e', '8')] },
            true,
            ['results'],
        ],
        [
            'persons above filter-only Results when they go first',
            { persons: [dashboard('p', '9')] },
            true,
            ['persons', 'results', 'loading-more'],
        ],
    ])('reveals %s', (_, loaded, personsFirst, expectedKeys) => {
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
                personsFirst,
            })
        )
        expect(sections.map((section) => section.key)).toEqual(expectedKeys)
    })

    test.each([
        [
            'while persons load',
            undefined,
            [
                ['ask-ai', ['ask-ai']],
                ['loading-more', ['loading-more']],
            ],
        ],
        ['when nothing else matches', [], [['ask-ai', ['ask-ai']]]],
        ['unless persons match', [dashboard('p', '9')], [['persons', ['item']]]],
    ])('offers PostHog AI %s', (_, persons, expected) => {
        const remote = emptyRemoteSlots()
        remote.results = { cache: { xyzzy: [] } }
        remote.events = { cache: { xyzzy: [] } }
        if (persons) {
            remote.persons = { cache: { xyzzy: persons } }
        }
        const sections = buildSections(
            input('search', {
                remote,
                remoteQueries: { results: 'xyzzy', events: 'xyzzy', persons: 'xyzzy' },
                localQuery: 'xyzzy',
                askAiQuestion: 'xyzzy',
            })
        )
        expect(sectionKinds(sections)).toEqual(expected)
    })

    it('ranks a person who matches every word of an email search above results that match fewer', () => {
        const person: SearchItem = {
            id: 'person-1',
            name: 'ada.l@example.com',
            displayName: 'ada.l@example.com',
            category: 'persons',
            record: { type: 'person', ref: '1' },
        }
        const remote = emptyRemoteSlots()
        remote.results = {
            cache: { 'ada.l@': [{ ...dashboard('a', '1'), name: 'Ada', rankKey: [-1, 0, 0, 0, -1, 0, 1, 0, 0] }] },
        }
        remote.persons = { cache: { 'ada.l@': [person] } }
        const sections = buildSections(
            input('search', {
                remote,
                remoteQueries: { results: 'ada.l@', persons: 'ada.l@' },
                localQuery: 'ada.l@',
                personsFirst: true,
            })
        )

        expect(sections.map((section) => section.key)).toEqual(['best-matches'])
        expect(sections[0].rows).toMatchObject([{ kind: 'item', section: 'persons', item: { id: 'person-1' } }])
    })

    test.each(['results', 'accounts'] as const)('waits for both ranked sources when %s loads first', (firstSource) => {
        const account: SearchItem = {
            id: 'account-1',
            name: 'Test organization',
            category: 'accounts',
            href: '/customer_analytics/accounts/account-1',
        }
        const remote = emptyRemoteSlots()
        const current = query({
            remoteQueries: { results: 'atlas.example.org', accounts: 'atlas.example.org' },
            localQuery: 'atlas.example.org',
        })
        const shown = query({ remoteQueries: { results: 'old' }, localQuery: 'old' })
        remote.results.cache.old = []
        remote[firstSource].cache['atlas.example.org'] = firstSource === 'accounts' ? [account] : []
        const sectionsInput = input('search', { remote, ...current })

        expect(sectionKinds(buildSections(sectionsInput))).toEqual([['results', ['skeleton', 'skeleton', 'skeleton']]])
        expect(resultsSettled(current, remote)).toBe(false)
        expect(pickDisplayedQuery(current, shown, remote)).toEqual({ query: shown, stale: true })

        remote.results.cache['atlas.example.org'] = []
        remote.accounts.cache['atlas.example.org'] = [account]
        const sections = buildSections(sectionsInput)
        expect(resultsSettled(current, remote)).toBe(true)
        expect(pickDisplayedQuery(current, shown, remote)).toEqual({ query: current, stale: false })
        expect(sections.map((section) => section.key)).toEqual(['best-matches'])
        expect(sections[0].rows).toMatchObject([{ kind: 'item', section: 'accounts', item: account }])
    })

    test.each([
        [
            'results',
            [{ ...dashboard('a', '1'), name: 'API usage', rankKey: [-1, 0, 0, 0, -1, 0, 1, 0, 0] }],
            ['notice', 'best-matches'],
        ],
        ['no results', [], []],
    ])('a search correction with %s shows the notice only above results', (_, results, keys) => {
        const remote = emptyRemoteSlots()
        remote.results.cache['api keys'] = results
        const sections = buildSections(
            input('search', {
                remote,
                remoteQueries: { results: 'api keys' },
                localQuery: 'api keys',
                searchCorrection: { from: 'api_keys', to: 'api keys' },
            })
        )

        expect(sections.map((section) => section.key)).toEqual(keys)
        if (keys.length) {
            expect(sections[0].rows).toEqual([
                expect.objectContaining({ reason: 'corrected', missing: ['api_keys'], shown: ['api keys'] }),
            ])
        }
    })

    it('with unified ranking, a domain search through the sections puts the account that owns the domain first', () => {
        const account: SearchItem = {
            id: 'account-1',
            name: 'Acme',
            category: 'accounts',
            itemType: 'account',
            identityFields: ['example.org'],
        }
        const remote = emptyRemoteSlots()
        remote.results.cache['example.org'] = [
            { ...dashboard('a', '1'), name: 'Example org signups', rankKey: [-2, 0, 0, 0, -2, 0, 1, 0, -1] },
        ]
        remote.accounts.cache['example.org'] = [account]
        const current = query({
            remoteQueries: { results: 'example.org', accounts: 'example.org' },
            localQuery: 'example.org',
        })

        const sections = buildSections(input('search', { remote, ...current, unifiedRanking: true }))

        expect(sections[0].rows[0]).toMatchObject({ kind: 'item', item: account })
    })

    it('shows saved objects when the Accounts request settles empty', () => {
        const remote = emptyRemoteSlots()
        remote.results.cache.billing = [{ ...dashboard('a', '1'), rankKey: [-1, 0, 0, 0, -1, 0, 2, 0, 0] }]
        remote.accounts.cache.billing = []
        const current = query({ remoteQueries: { results: 'billing', accounts: 'billing' }, localQuery: 'billing' })

        expect(resultsSettled(current, remote)).toBe(true)
        expect(sectionKinds(buildSections(input('search', { remote, ...current })))).toEqual([
            ['best-matches', ['item']],
        ])
    })

    test.each([
        ['no product shares its name', 'Personal API keys', ['best-matches'], 'Personal API keys'],
        ['a product has its name', 'API keys', ['best-matches', 'settings'], 'API keys'],
    ])('ranks an exact-match setting with the results when %s', (_, settingName, keys, first) => {
        const setting: SearchItem = {
            id: 'settings-api-keys',
            name: `User: ${settingName} (api keys)`,
            displayName: settingName,
            category: 'settings',
        }
        const products: SearchItem[] =
            settingName === 'API keys' ? [{ id: 'product-api-keys', name: 'API keys', category: 'products' }] : []
        const remote = emptyRemoteSlots()
        remote.results = {
            cache: {
                'api keys': [{ ...dashboard('a', '1'), name: 'Ada board', rankKey: [-1, 0, 0, 0, -1, 0, 1, 0, 0] }],
            },
        }
        const sections = buildSections(
            input('search', {
                local: { ...emptyLocal(), settings: [setting], products },
                remote,
                remoteQueries: { results: 'api keys' },
                localQuery: 'api keys',
            })
        )

        expect(sections.map((section) => section.key)).toEqual(keys)
        const firstItem = sections[0].rows[0]
        expect(firstItem.kind === 'item' ? String(firstItem.item.displayName || firstItem.item.name) : null).toBe(first)
    })

    it('with unified ranking, a pasted snake_case name ranks its matching setting first', () => {
        const setting: SearchItem = {
            id: 'settings-api-keys',
            name: 'User: Personal API keys (api keys)',
            displayName: 'Personal API keys',
            category: 'settings',
        }
        const products: SearchItem[] = [
            { id: 'product-endpoints', name: 'Endpoints', category: 'products', searchKeywords: ['api'] },
        ]
        const remote = emptyRemoteSlots()
        remote.results.cache.personal_api_keys = []
        const sections = buildSections(
            input('search', {
                local: { ...emptyLocal(), settings: [setting], products },
                remote,
                remoteQueries: { results: 'personal_api_keys' },
                localQuery: 'personal_api_keys',
                unifiedRanking: true,
            })
        )

        expect(sections[0].rows[0]).toMatchObject({ kind: 'item', item: setting })
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
