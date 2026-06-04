import { TaxonomicDefinitionTypes } from 'lib/components/TaxonomicFilter/types'

import { composeSuggestedItems } from './composeSuggestedItems'

const named = (name: string): TaxonomicDefinitionTypes => ({ name }) as TaxonomicDefinitionTypes
const names = (items: TaxonomicDefinitionTypes[]): string[] => items.map((i) => ('name' in i ? (i.name as string) : ''))

describe('composeSuggestedItems', () => {
    const recents = [named('r1'), named('r2'), named('r3'), named('r4')]
    const pinned = [named('p1'), named('p2'), named('p3'), named('p4')]
    const local = [named('promoted-a'), named('promoted-b')]

    it('with no query: top-3 recents, then top-3 pinned, then local options', () => {
        const { items, count } = composeSuggestedItems({
            searchQuery: '',
            localResults: local,
            localCount: local.length,
            contextRecents: recents,
            contextPinned: pinned,
            recentMatches: [],
            pinnedMatches: [],
        })
        expect(names(items)).toEqual(['r1', 'r2', 'r3', 'p1', 'p2', 'p3', 'promoted-a', 'promoted-b'])
        expect(count).toBe(8)
    })

    it('with a query: recent matches, then pinned matches, then local — prefixes ignored', () => {
        const { items, count } = composeSuggestedItems({
            searchQuery: 'foo',
            localResults: [named('foo-event')],
            localCount: 1,
            contextRecents: recents,
            contextPinned: pinned,
            recentMatches: [named('r-match')],
            pinnedMatches: [named('p-match')],
        })
        expect(names(items)).toEqual(['r-match', 'p-match', 'foo-event'])
        expect(count).toBe(3)
    })

    it('promotes a matching property to the front when the query is a promoted term', () => {
        const { items } = composeSuggestedItems({
            searchQuery: 'url',
            localResults: [named('some_other_url'), named('$current_url')],
            localCount: 2,
            contextRecents: [],
            contextPinned: [],
            recentMatches: [],
            pinnedMatches: [],
        })
        expect(names(items)[0]).toBe('$current_url')
    })

    it.each([
        { label: 'no query', searchQuery: '', expected: 3 + 3 + 2 },
        { label: 'with query', searchQuery: 'x', expected: 1 + 1 + 2 },
    ])('count is the sum of the rendered segments ($label)', ({ searchQuery, expected }) => {
        const { count } = composeSuggestedItems({
            searchQuery,
            localResults: local,
            localCount: local.length,
            contextRecents: recents,
            contextPinned: pinned,
            recentMatches: [named('rm')],
            pinnedMatches: [named('pm')],
        })
        expect(count).toBe(expected)
    })
})
