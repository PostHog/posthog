import { SETTINGS_THEME_ITEM_ID, canOpenInNewTab, filterSearchItems } from './utils'

interface TestItem {
    name: string
    displayName?: string
    category: string
    searchKeywords?: string[]
}

const makeItem = (name: string, category = 'tools', extra: Partial<TestItem> = {}): TestItem => ({
    name,
    category,
    ...extra,
})

const items: TestItem[] = [
    makeItem('Event definitions', 'data-management'),
    makeItem('Property definitions', 'data-management'),
    makeItem('Feature flags', 'tools'),
    makeItem('Cohorts', 'tools'),
    makeItem('Dashboards', 'tools'),
    makeItem('Session recordings', 'tools'),
    makeItem('Web analytics', 'tools'),
    makeItem('Experiments', 'tools'),
    makeItem('Surveys', 'tools'),
    makeItem('Product analytics', 'tools'),
    makeItem('Error tracking', 'tools'),
    makeItem('Data warehouse', 'tools', { searchKeywords: ['sql', 'query', 'database'] }),
]

const names = (results: TestItem[]): string[] => results.map((r) => r.name)

describe('filterSearchItems', () => {
    it('returns all items for empty query', () => {
        expect(filterSearchItems(items, '')).toEqual(items)
        expect(filterSearchItems(items, '  ')).toEqual(items)
    })

    describe('exact and near-exact matching', () => {
        it('matches by exact name', () => {
            expect(names(filterSearchItems(items, 'Cohorts'))).toContain('Cohorts')
        })

        it('matches case-insensitively', () => {
            expect(names(filterSearchItems(items, 'cohorts'))).toContain('Cohorts')
        })

        it('matches partial name', () => {
            expect(names(filterSearchItems(items, 'dash'))).toContain('Dashboards')
        })
    })

    describe('fuzzy matching (the original bug)', () => {
        it('"events" matches "Event definitions"', () => {
            const results = filterSearchItems(items, 'events')
            expect(names(results)).toContain('Event definitions')
        })

        it('"event" matches "Event definitions"', () => {
            const results = filterSearchItems(items, 'event')
            expect(names(results)).toContain('Event definitions')
        })

        it('"properties" matches "Property definitions"', () => {
            const results = filterSearchItems(items, 'properties')
            expect(names(results)).toContain('Property definitions')
        })

        it('"flag" matches "Feature flags"', () => {
            const results = filterSearchItems(items, 'flag')
            expect(names(results)).toContain('Feature flags')
        })

        it('"experiment" matches "Experiments"', () => {
            const results = filterSearchItems(items, 'experiment')
            expect(names(results)).toContain('Experiments')
        })
    })

    describe('searchKeywords', () => {
        it('matches on searchKeywords', () => {
            const results = filterSearchItems(items, 'sql')
            expect(names(results)).toContain('Data warehouse')
        })

        it('matches on keyword "database"', () => {
            const results = filterSearchItems(items, 'database')
            expect(names(results)).toContain('Data warehouse')
        })
    })

    describe('category matching', () => {
        it('matches on category', () => {
            const results = filterSearchItems(items, 'data-management')
            expect(names(results)).toContain('Event definitions')
            expect(names(results)).toContain('Property definitions')
        })
    })

    describe('no false positives', () => {
        it('does not match completely unrelated terms', () => {
            const results = filterSearchItems(items, 'xyzzyplugh')
            expect(results).toEqual([])
        })
    })
})

// Cmd/Ctrl+Enter routes through this, so a false positive on an action item runs that action
// instead of opening a background tab, which in the case of "Log out" ends the session.
describe('canOpenInNewTab', () => {
    const cases: [label: string, item: { id: string; href?: string; onSelect?: () => void }, expected: boolean][] = [
        ['allows a plain navigable result', { id: 'insight-1', href: '/insights/1' }, true],
        ['blocks an action-only result such as "Log out"', { id: 'misc-logout', onSelect: jest.fn() }, false],
        [
            'blocks an action that also carries an href',
            { id: 'new-sql-query-tab', href: '/sql', onSelect: jest.fn() },
            false,
        ],
        [
            'blocks the theme row, which navigates but toggles instead',
            { id: SETTINGS_THEME_ITEM_ID, href: '/settings/theme' },
            false,
        ],
        ['blocks a result with nothing to open', { id: 'no-href' }, false],
    ]

    it.each(cases)('%s', (_label, item, expected) => {
        expect(canOpenInNewTab(item)).toBe(expected)
    })
})
