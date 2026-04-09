import { mapToTopN } from './detachedElementTracker'

describe('mapToTopN', () => {
    it.each([
        {
            label: 'empty map returns empty object',
            map: new Map<string, number>(),
            limit: 10,
            expected: {},
        },
        {
            label: 'fewer entries than limit returns all',
            map: new Map([
                ['div', 100],
                ['span', 50],
            ]),
            limit: 10,
            expected: { div: 100, span: 50 },
        },
        {
            label: 'more entries than limit returns top N by count',
            map: new Map([
                ['div', 100],
                ['span', 50],
                ['p', 200],
                ['a', 10],
            ]),
            limit: 2,
            expected: { p: 200, div: 100 },
        },
        {
            label: 'exactly limit entries returns all',
            map: new Map([
                ['div', 100],
                ['span', 50],
            ]),
            limit: 2,
            expected: { div: 100, span: 50 },
        },
        {
            label: 'ties are broken alphabetically',
            map: new Map([
                ['span', 100],
                ['div', 100],
                ['p', 100],
            ]),
            limit: 2,
            expected: { div: 100, p: 100 },
        },
        {
            label: 'limit of zero returns empty object',
            map: new Map([['div', 100]]),
            limit: 0,
            expected: {},
        },
    ])('$label', ({ map, limit, expected }) => {
        expect(mapToTopN(map, limit)).toEqual(expected)
    })
})
