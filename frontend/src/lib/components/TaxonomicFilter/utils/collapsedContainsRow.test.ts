import { containsShortcutLeads } from './collapsedContainsRow'

describe('containsShortcutLeads', () => {
    it.each([
        { query: 'country', otherMatchCount: 2, leads: false },
        { query: 'email', otherMatchCount: 1, leads: false },
        { query: 'checkout', otherMatchCount: 0, leads: true },
        { query: '/pricing', otherMatchCount: 3, leads: true },
        { query: 'example.com', otherMatchCount: 3, leads: true },
        { query: 'https:', otherMatchCount: 3, leads: true },
        { query: '  pricing  ', otherMatchCount: 0, leads: true },
    ])('$query with $otherMatchCount other matches leads: $leads', ({ query, otherMatchCount, leads }) => {
        expect(containsShortcutLeads(query, otherMatchCount)).toBe(leads)
    })
})
