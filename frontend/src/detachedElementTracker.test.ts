import { mapToTopN, shouldCaptureDetachedElements } from './detachedElementTracker'

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

describe('shouldCaptureDetachedElements', () => {
    it.each([
        {
            label: 'skips when zero even on first scan',
            currentCount: 0,
            previousCount: null,
            expected: false,
        },
        {
            label: 'first scan with nonzero count always captures',
            currentCount: 5,
            previousCount: null,
            expected: true,
        },
        {
            label: 'skips when count is unchanged',
            currentCount: 3,
            previousCount: 3,
            expected: false,
        },
        {
            label: 'captures when count increases',
            currentCount: 5,
            previousCount: 3,
            expected: true,
        },
        {
            label: 'captures when count decreases',
            currentCount: 2,
            previousCount: 5,
            expected: true,
        },
        {
            label: 'skips when count stays at zero',
            currentCount: 0,
            previousCount: 0,
            expected: false,
        },
        {
            label: 'captures when count goes from zero to nonzero',
            currentCount: 1,
            previousCount: 0,
            expected: true,
        },
        {
            label: 'skips when count goes from nonzero to zero',
            currentCount: 0,
            previousCount: 7,
            expected: false,
        },
    ])('$label', ({ currentCount, previousCount, expected }) => {
        expect(shouldCaptureDetachedElements(currentCount, previousCount)).toBe(expected)
    })
})
