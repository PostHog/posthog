import {
    asNonEmptyString,
    containsUnstableGeneratedId,
    elementToQuery,
    joinWithUiHost,
    safeFetch,
    unescapeCssSelector,
} from './utils'

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

    describe('unescapeCssSelector', () => {
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
            {
                // escaped characters other than dots must round-trip, not be mangled into dots
                input: '[data-id="base-ui-\\:rg\\:-viewport"] > [data-has-overflow-y=""]',
                expected: '[data-id="base-ui-:rg:-viewport"] > [data-has-overflow-y=""]',
            },
            {
                // CSS.escape emits hex code-point escapes for leading digits, e.g. CSS.escape('123-foo')
                input: '[data-id="\\31 23-foo"]',
                expected: '[data-id="123-foo"]',
            },
        ]
        testCases.forEach(({ input, expected }) => {
            it(`should unescape "${input}" to "${expected}"`, () => {
                const result = unescapeCssSelector(input)
                expect(result).toBe(expected)
            })
        })
    })

    describe('containsUnstableGeneratedId', () => {
        const testCases: Array<{ value: string; expected: boolean }> = [
            { value: 'base-ui-:rg:-viewport', expected: true },
            { value: ':r5:', expected: true },
            { value: 'radix-:R1d6:', expected: true },
            { value: 'base-ui-«r5»-viewport', expected: true },
            { value: 'sidebar-viewport', expected: false },
            { value: 'session.recording.preview', expected: false },
        ]
        it.each(testCases)('$value -> $expected', ({ value, expected }) => {
            expect(containsUnstableGeneratedId(value)).toBe(expected)
        })
    })

    describe('elementToQuery', () => {
        it('does not build selectors from useId-derived data attributes', () => {
            document.body.innerHTML = `
                <div data-id="base-ui-:rg:-viewport">
                    <div data-has-overflow-y=""><button>hi</button></div>
                </div>
            `
            const element = document.querySelector('[data-has-overflow-y]') as HTMLElement
            const selector = elementToQuery(element, [])
            expect(selector).toBeTruthy()
            expect(selector).not.toContain('base-ui-')
        })

        it('uses stable data attributes via finder', () => {
            document.body.innerHTML = `
                <div data-id="sidebar-viewport">
                    <div data-has-overflow-y=""><button>hi</button></div>
                </div>
            `
            const element = document.querySelector('[data-id="sidebar-viewport"]') as HTMLElement
            const selector = elementToQuery(element, [])
            expect(selector).toContain('[data-id="sidebar-viewport"]')
        })
    })

    describe('safeFetch', () => {
        const originalFetch = global.fetch

        afterEach(() => {
            global.fetch = originalFetch
        })

        it('passes a real Response through unchanged', async () => {
            const realResponse = new Response('{}', { status: 200 })
            global.fetch = jest.fn(() => Promise.resolve(realResponse)) as jest.Mock

            const result = await safeFetch('https://example.com/api')

            expect(result).toBe(realResponse)
        })

        it('passes a response-like object through unchanged', async () => {
            const responseLike = { status: 200, ok: true, json: () => Promise.resolve({}) }
            global.fetch = jest.fn(() => Promise.resolve(responseLike)) as jest.Mock

            const result = await safeFetch('https://example.com/api')

            expect(result).toBe(responseLike)
        })

        it.each([undefined, null, 'not-a-response'])(
            'normalizes a non-object value (%p) into a synthetic failed response',
            async (resolved) => {
                global.fetch = jest.fn(() => Promise.resolve(resolved)) as jest.Mock

                const result = await safeFetch('https://example.com/api')

                expect(result).toBeInstanceOf(Response)
                expect(result.ok).toBe(false)
                expect(result.status).toBe(502)
            }
        )
    })
})
