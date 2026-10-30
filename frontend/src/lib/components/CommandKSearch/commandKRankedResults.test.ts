import { SearchItem } from 'lib/components/Search/searchItems'

import { buildRankedResults } from './commandKRankedResults'
import type { CommandKSection } from './commandKSections'

const result = (
    id: string,
    name: string,
    type: string,
    rankKey: number[],
    match: Partial<NonNullable<SearchItem['searchMatch']>> = {}
): SearchItem => ({
    id,
    name,
    category: 'results',
    record: { type, ref: id, path: `Unfiled/${name}` },
    rankKey,
    searchMatch: {
        matchedAllWords: true,
        matchedWords: [],
        typeCount: 1,
        countsCapped: false,
        withTypos: false,
        ...match,
    },
})

const product = (name: string, searchKeywords: string[] = []): SearchItem => ({
    id: `product-${name}`,
    name,
    category: 'products',
    searchKeywords,
})

const exactWordRank = (created: number): number[] => [-1, 0, 0, 0, -1, 0, 2, 0, -created]

const account = (id: string, name: string): SearchItem => ({ id, name, category: 'accounts', itemType: 'account' })

const summary = (sections: CommandKSection[]): string[] =>
    sections.map((section) => {
        const rows = section.rows.map((row) => {
            if (row.kind === 'item') {
                return `${row.item.name}${row.duplicates ? ` +${row.duplicates}` : ''}`
            }
            if (row.kind === 'notice') {
                return `(${row.reason}: ${row.missing.join(' ')} -> ${row.shown.join(' ')})`
            }
            return row.kind === 'scope' || row.kind === 'message'
                ? `(${row.kind === 'scope' ? row.label : row.text})`
                : row.kind
        })
        return `${section.label || section.key}: ${rows.join(', ')}`
    })

describe('buildRankedResults', () => {
    test.each([
        {
            name: 'a product matched by an alias leads the best matches',
            query: 'recordings',
            results: [result('1', 'Recordings funnel', 'insight', exactWordRank(2))],
            products: [product('Session replay', ['recordings']), product('Surveys')],
            expected: ['Results: Session replay, Recordings funnel'],
        },
        {
            name: 'a product leads a tab of another product with the same name, and they do not collapse',
            query: 'playground',
            results: [],
            products: [
                {
                    ...product('Business knowledge Playground'),
                    displayName: 'Playground',
                    parentName: 'Business knowledge',
                },
                product('Playground'),
            ],
            expected: ['Results: Playground, Business knowledge Playground'],
        },
        {
            name: 'a product that matches fewer words than the saved objects stays out',
            query: 'flags billing',
            results: [result('1', 'Feature flags billing', 'insight', [-2, 0, 0, 0, -2, 0, 3, 0, -1])],
            products: [product('Feature flags')],
            expected: ['Results: Feature flags billing'],
        },
        {
            name: 'same-name rows collapse and the see-all count covers what is hidden',
            query: 'retention',
            results: [
                result('1', 'Retention', 'insight', exactWordRank(9), { typeCount: 10 }),
                result('2', 'Retention', 'insight', exactWordRank(8), { typeCount: 10 }),
                result('3', 'Retention by plan', 'insight', exactWordRank(7), { typeCount: 10 }),
                result('4', 'Retention weekly', 'insight', exactWordRank(6), { typeCount: 10 }),
                result('5', 'Retention (copy)', 'insight', exactWordRank(5), { typeCount: 10 }),
                result('6', 'Retention daily', 'insight', exactWordRank(4), { typeCount: 10 }),
                result('7', 'Retention monthly', 'insight', exactWordRank(3), { typeCount: 10 }),
                result('10', 'Retention by country', 'insight', exactWordRank(3), { typeCount: 10 }),
                result('11', 'Retention by device', 'insight', exactWordRank(3), { typeCount: 10 }),
                result('12', 'Retention by browser', 'insight', exactWordRank(3), { typeCount: 10 }),
                result('8', 'Retention board', 'dashboard', exactWordRank(2), { typeCount: 2 }),
                result('9', 'Retention deep dive', 'dashboard', exactWordRank(1), { typeCount: 2 }),
            ],
            products: [],
            expected: [
                'Best matches: Retention +2, Retention board',
                'Insights: Retention by plan, Retention weekly, Retention daily, (See all 10 insights)',
                'Dashboards: Retention deep dive',
            ],
        },
        {
            name: 'a type whose results collapse into one best match keeps its see-all row',
            query: 'revenue',
            results: [
                ...[30, 29, 28].map((created) =>
                    result(`insight-${created}`, 'Revenue', 'insight', exactWordRank(created), { typeCount: 50 })
                ),
                ...['a', 'b', 'c', 'd', 'e'].map((suffix, index) =>
                    result(`dashboard-${suffix}`, `Revenue board ${suffix}`, 'dashboard', exactWordRank(20 - index), {
                        typeCount: 5,
                    })
                ),
                ...['a', 'b', 'c', 'd'].map((suffix, index) =>
                    result(`notebook-${suffix}`, `Revenue notes ${suffix}`, 'notebook', exactWordRank(10 - index), {
                        typeCount: 4,
                    })
                ),
            ],
            products: [],
            expected: [
                'Best matches: Revenue +2, Revenue board a, Revenue notes a',
                'Dashboards: Revenue board b, Revenue board c, Revenue board d, (See all 5 dashboards)',
                'Notebooks: Revenue notes b, Revenue notes c, Revenue notes d',
                'Insights: (See all 50 insights)',
            ],
        },
        {
            name: 'a product that matches every word hides the dropped-words notice',
            query: 'session replay',
            results: [
                result('1', 'Replay notes', 'notebook', [-1, 0, 0, 0, -1, 0, 2, 0, -1], {
                    matchedAllWords: false,
                    matchedWords: ['replay'],
                }),
            ],
            products: [product('Session replay')],
            expected: ['Results: Session replay'],
        },
        {
            name: 'results that match only some words say which words were used',
            query: 'xyzzy report',
            results: [
                result('1', 'Weekly report', 'insight', [-1, 0, 0, 1, -1, 1, 5, 0, -1], {
                    matchedAllWords: false,
                    matchedWords: ['report'],
                }),
            ],
            products: [],
            expected: ['notice: (partial: xyzzy -> report)', 'Results: Weekly report'],
        },
        {
            name: 'an account identity match hides the dropped-words notice and leads partial matches',
            query: 'billing customer',
            results: [
                result('1', 'Customer report', 'insight', [-1, 0, 0, 1, -1, 0, 5, 0, -1], {
                    matchedAllWords: false,
                    matchedWords: ['customer'],
                }),
            ],
            products: [product('Customer analytics')],
            accounts: [account('account-1', 'Test organization')],
            expected: ['Results: Test organization'],
        },
        {
            name: 'an account match hides the close-spellings notice',
            query: 'dashbord',
            results: [
                result('1', 'Dashboard', 'dashboard', [-1, 1, 0, 0, 0, 0, 5, 0, -1], {
                    matchedWords: ['dashbord'],
                    withTypos: true,
                }),
            ],
            products: [],
            accounts: [account('account-1', 'Dashbord tools')],
            expected: ['Results: Dashbord tools'],
        },
        {
            name: 'an account can rank without saved objects or a matching display name',
            query: 'atlas.example.org',
            results: [],
            products: [],
            accounts: [account('account-1', 'Test organization')],
            expected: ['Results: Test organization'],
        },
        {
            name: 'distinct accounts with the same name stay separate and get no file-system scope row',
            query: 'billing',
            results: [1, 2, 3, 4, 5, 6].map((n) =>
                result(`insight-${n}`, `Billing insight ${n}`, 'insight', exactWordRank(n), { typeCount: 6 })
            ),
            products: [],
            accounts: [1, 2, 3, 4].map((n) => account(`account-${n}`, 'Billing')),
            expected: [
                'Best matches: Billing, Billing insight 6',
                'Accounts: Billing, Billing, Billing',
                'Insights: Billing insight 5, Billing insight 4, Billing insight 3, (See all 6 insights)',
            ],
        },
        {
            name: 'a group of persons gets no see-all row, because persons are not a file system type',
            query: 'ada',
            results: [1, 2, 3, 4].map((n) =>
                result(`insight-${n}`, `Ada insight ${n}`, 'insight', exactWordRank(n), { typeCount: 9 })
            ),
            products: [],
            persons: ['a', 'b', 'c', 'd', 'e'].map((suffix) => ({
                id: `person-${suffix}`,
                name: `ada@${suffix}.example.com`,
                category: 'persons',
                record: { type: 'person', ref: suffix },
            })),
            expected: [
                'Best matches: Ada insight 4, ada@a.example.com',
                'Insights: Ada insight 3, Ada insight 2, Ada insight 1, (See all 9 insights)',
                'Persons: ada@b.example.com, ada@c.example.com, ada@d.example.com',
            ],
        },
    ])('$name', ({ query, results, products, persons = [], accounts = [], expected }) => {
        expect(
            summary(
                buildRankedResults({
                    query,
                    highlightWords: query.split(' '),
                    results,
                    products,
                    persons,
                    accounts,
                    state: 'ready',
                    scoped: false,
                })
            )
        ).toEqual(expected)
    })
})
