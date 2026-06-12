import { asNonEmptyString, joinWithUiHost, makeNavigateWrapper, slashDotDataAttrUnescape } from './utils'

jest.mock('~/toolbar/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

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

    describe('makeNavigateWrapper', () => {
        let originalPushState: History['pushState']
        let originalReplaceState: History['replaceState']

        beforeEach(() => {
            originalPushState = window.history.pushState
            originalReplaceState = window.history.replaceState
        })

        afterEach(() => {
            window.history.pushState = originalPushState
            window.history.replaceState = originalReplaceState
        })

        it('calls onNavigate after pushState/replaceState and unwraps cleanly', () => {
            const onNavigate = jest.fn()
            const unwrap = makeNavigateWrapper(onNavigate, '__test_navigate_wrapper__')()

            window.history.pushState({}, '', '/pushed')
            window.history.replaceState({}, '', '/replaced')
            expect(onNavigate).toHaveBeenCalledTimes(2)

            unwrap()
            expect(window.history.pushState).toBe(originalPushState)
            expect(window.history.replaceState).toBe(originalReplaceState)
        })

        it('does not let a throwing original break the host page navigation', () => {
            // Simulate a host site that also patched history and throws "Illegal invocation".
            window.history.pushState = (() => {
                throw new TypeError('Illegal invocation')
            }) as History['pushState']
            const onNavigate = jest.fn()
            makeNavigateWrapper(onNavigate, '__test_navigate_wrapper_throws__')()

            expect(() => window.history.pushState({}, '', '/pushed')).not.toThrow()
            expect(onNavigate).not.toHaveBeenCalled()
        })

        it('does not let a throwing onNavigate propagate into the host page', () => {
            const onNavigate = jest.fn(() => {
                throw new Error('boom')
            })
            makeNavigateWrapper(onNavigate, '__test_navigate_wrapper_cb_throws__')()

            expect(() => window.history.pushState({}, '', '/pushed')).not.toThrow()
            expect(onNavigate).toHaveBeenCalledTimes(1)
        })
    })
})
