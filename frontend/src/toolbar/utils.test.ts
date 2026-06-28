import { asNonEmptyString, joinWithUiHost, makeNavigateWrapper, safeFetch, slashDotDataAttrUnescape } from './utils'

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

    describe('makeNavigateWrapper', () => {
        const nativePushState = History.prototype.pushState
        const nativeReplaceState = History.prototype.replaceState
        let cleanups: Array<() => void>

        beforeEach(() => {
            cleanups = []
        })

        afterEach(() => {
            cleanups.forEach((cleanup) => cleanup())
            window.history.pushState = nativePushState
            window.history.replaceState = nativeReplaceState
        })

        const register = (onNavigate: () => void): void => {
            cleanups.push(makeNavigateWrapper(onNavigate)())
        }

        it('patches history.pushState only once regardless of how many wrappers register', () => {
            register(() => {})
            const patchedAfterFirst = window.history.pushState

            // A second logic asking to react to navigation must not re-wrap the native method —
            // double-wrapping is what produces the "Illegal invocation" through chained .call(this).
            register(() => {})

            expect(window.history.pushState).toBe(patchedAfterFirst)
        })

        it('notifies every registered callback on pushState and replaceState', () => {
            const first = jest.fn()
            const second = jest.fn()
            register(first)
            register(second)

            window.history.pushState(null, '', '/pushed')
            window.history.replaceState(null, '', '/replaced')

            expect(first).toHaveBeenCalledTimes(2)
            expect(second).toHaveBeenCalledTimes(2)
        })

        it('restores native methods once all wrappers are removed', () => {
            register(() => {})
            register(() => {})
            expect(window.history.pushState).not.toBe(nativePushState)

            cleanups.forEach((cleanup) => cleanup())
            cleanups = []

            expect(window.history.pushState).toBe(nativePushState)
            expect(window.history.replaceState).toBe(nativeReplaceState)
        })

        it('falls back to the native method and still notifies when the wrapped call throws', () => {
            // Emulate a customer-page wrapper that rejects the `this` we forward, like an SPA router
            // whose history wrapper throws "Illegal invocation".
            window.history.pushState = function throwingPushState(): void {
                throw new TypeError('Illegal invocation')
            }
            const onNavigate = jest.fn()
            register(onNavigate)

            expect(() => window.history.pushState(null, '', '/pushed')).not.toThrow()
            expect(onNavigate).toHaveBeenCalledTimes(1)
            expect(window.location.pathname).toBe('/pushed')
        })
    })
})
