import { asNonEmptyString, getRect, joinWithUiHost, safeGetBoundingClientRect, slashDotDataAttrUnescape } from './utils'

describe('utils', () => {
    describe('asNonEmptyString', () => {
        const testCases: Array<{ input: unknown; expected: string | null }> = [
            { input: 'hello', expected: 'hello' },
            { input: '', expected: null },
            { input: null, expected: null },
            { input: undefined, expected: null },
            { input: true, expected: null },
            { input: false, expected: null },
            { input: 0, expected: null },
            { input: 1, expected: null },
            { input: {}, expected: null },
            { input: [], expected: null },
            { input: ['a'], expected: null },
        ]
        it.each(testCases)('$input -> $expected', ({ input, expected }) => {
            expect(asNonEmptyString(input)).toBe(expected)
        })
    })

    describe('joinWithUiHost', () => {
        const testCases: Array<{ uiHost: string; path: string; expected: string }> = [
            {
                uiHost: 'https://us.posthog.com',
                path: '/settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com/',
                path: '/settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com///',
                path: 'settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com',
                path: 'settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com/',
                path: '///settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com',
                path: `${'/settings/project'}#heatmaps`,
                expected: 'https://us.posthog.com/settings/project#heatmaps',
            },
            { uiHost: 'https://us.posthog.com', path: '?a=1', expected: 'https://us.posthog.com/?a=1' },
            { uiHost: 'https://us.posthog.com', path: '#hash', expected: 'https://us.posthog.com/#hash' },
            { uiHost: 'https://us.posthog.com', path: 'https://example.com/x', expected: 'https://example.com/x' },
            { uiHost: 'https://us.posthog.com', path: '//example.com/x', expected: '//example.com/x' },
            { uiHost: '', path: '/settings/project', expected: '/settings/project' },
        ]

        testCases.forEach(({ uiHost, path, expected }) => {
            it(`joins "${uiHost}" + "${path}"`, () => {
                expect(joinWithUiHost(uiHost, path)).toBe(expected)
            })
        })
    })

    describe('safeGetBoundingClientRect', () => {
        const emptyRect = { bottom: 0, height: 0, left: 0, right: 0, top: 0, width: 0, x: 0, y: 0 }

        it('returns empty rect for null', () => {
            expect(safeGetBoundingClientRect(null)).toMatchObject(emptyRect)
        })

        it('returns empty rect for undefined', () => {
            expect(safeGetBoundingClientRect(undefined)).toMatchObject(emptyRect)
        })

        it('returns empty rect when getBoundingClientRect is missing', () => {
            // Customer pages can mount custom elements / polyfilled wrappers that lack the layout API.
            expect(safeGetBoundingClientRect({})).toMatchObject(emptyRect)
            expect(safeGetBoundingClientRect({ getBoundingClientRect: 'not-a-function' })).toMatchObject(emptyRect)
        })

        it('returns empty rect when getBoundingClientRect throws', () => {
            const throwingEl = {
                getBoundingClientRect: () => {
                    throw new Error('detached')
                },
            }
            expect(safeGetBoundingClientRect(throwingEl)).toMatchObject(emptyRect)
        })

        it('delegates to the real getBoundingClientRect', () => {
            const fakeRect = { bottom: 10, height: 10, left: 0, right: 10, top: 0, width: 10, x: 0, y: 0 }
            const el = { getBoundingClientRect: () => fakeRect }
            expect(safeGetBoundingClientRect(el)).toBe(fakeRect)
        })
    })

    describe('getRect', () => {
        it('returns zeroed rect when element lacks getBoundingClientRect', () => {
            // Repro for the toolbar TypeError that fires on customer DOMs containing nodes
            // typed as HTMLElement but missing the layout API.
            const malformed = {} as unknown as HTMLElement
            expect(getRect(malformed)).toEqual({
                x: 0,
                y: 0,
                width: 0,
                height: 0,
                top: 0,
                right: 0,
                bottom: 0,
                left: 0,
            })
        })
    })

    describe('slashDotDataAttrUnescape', () => {
        const testCases = [
            {
                input: 'div[data-attr="test"]',
                expected: 'div[data-attr="test"]',
            },
            {
                input: 'div[data-attr="test\\."]',
                expected: 'div[data-attr="test."]',
            },
            {
                input: 'div[data-something="test\\.test\\.test"]',
                expected: 'div[data-something="test.test.test"]',
            },
            {
                input: '.tomato div[data-something="test\\.test\\.test"]',
                expected: '.tomato div[data-something="test.test.test"]',
            },
            {
                input: '\\.tomato div[data-something="test\\.test\\.test"]',
                expected: '.tomato div[data-something="test.test.test"]',
            },
        ]
        testCases.forEach(({ input, expected }) => {
            it(`should unescape "${input}" to "${expected}"`, () => {
                const result = slashDotDataAttrUnescape(input)
                expect(result).toBe(expected)
            })
        })
    })
})
