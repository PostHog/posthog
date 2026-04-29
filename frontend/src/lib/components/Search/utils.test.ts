import { filterSearchItems } from './utils'

interface TestItem {
    name: string
    displayName?: string
    category: string
    searchKeywords?: string[]
}

const makeItem = (name: string, category = 'apps', extra: Partial<TestItem> = {}): TestItem => ({
    name,
    category,
    ...extra,
})

const items: TestItem[] = [
    makeItem('Event definitions', 'data-management'),
    makeItem('Property definitions', 'data-management'),
    makeItem('Feature flags', 'apps'),
    makeItem('Cohorts', 'apps'),
    makeItem('Dashboards', 'apps'),
    makeItem('Session recordings', 'apps'),
    makeItem('Web analytics', 'apps'),
    makeItem('Experiments', 'apps'),
    makeItem('Surveys', 'apps'),
    makeItem('Product analytics', 'apps'),
    makeItem('Error tracking', 'apps'),
    makeItem('Data warehouse', 'apps', { searchKeywords: ['sql', 'query', 'database'] }),
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
