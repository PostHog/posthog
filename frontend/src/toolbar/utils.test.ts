import type { PostHog } from 'posthog-js'

import {
    asNonEmptyString,
    joinWithUiHost,
    safeFetch,
    safeOverrideFeatureFlags,
    slashDotDataAttrUnescape,
} from './utils'

describe('utils', () => {
    describe('safeOverrideFeatureFlags', () => {
        it('calls overrideFeatureFlags on the host instance when supported', () => {
            const overrideFeatureFlags = jest.fn()
            const clientPostHog = { featureFlags: { overrideFeatureFlags } } as unknown as PostHog

            expect(safeOverrideFeatureFlags(clientPostHog, false)).toBe(true)
            expect(overrideFeatureFlags).toHaveBeenCalledWith(false)
        })

        it('does not throw when the host posthog-js predates overrideFeatureFlags', () => {
            // Older SDKs on customer sites lack this method entirely.
            const clientPostHog = { featureFlags: {} } as unknown as PostHog

            expect(() => safeOverrideFeatureFlags(clientPostHog, false)).not.toThrow()
            expect(safeOverrideFeatureFlags(clientPostHog, false)).toBe(false)
        })

        it('is a no-op when there is no host instance', () => {
            expect(safeOverrideFeatureFlags(null, { flags: { a: true } })).toBe(false)
            expect(safeOverrideFeatureFlags(undefined, { flags: { a: true } })).toBe(false)
        })
    })

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
})
