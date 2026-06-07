import { asNonEmptyString, joinWithUiHost, parseJsonResponse, slashDotDataAttrUnescape } from './utils'

describe('utils', () => {
    describe('parseJsonResponse', () => {
        const successCases: Array<{ body: string; status: number; expected: unknown }> = [
            { body: JSON.stringify({ access_token: 'abc' }), status: 200, expected: { access_token: 'abc' } },
            // JSON error bodies on a non-2xx status are still parsed (e.g. OAuth `{ "error": … }`).
            { body: JSON.stringify({ error: 'invalid_grant' }), status: 400, expected: { error: 'invalid_grant' } },
        ]
        it.each(successCases)('resolves a JSON body (status $status)', async ({ body, status, expected }) => {
            const res = new Response(body, { status })
            await expect(parseJsonResponse(res)).resolves.toEqual(expected)
        })

        const errorCases: Array<{ body: string; status: number; pattern: RegExp }> = [
            {
                body: '<!DOCTYPE html><html><body>Login</body></html>',
                status: 200,
                pattern: /non-JSON response \(status 200\)/,
            },
            // The thrown error includes the status and a body snippet, not a raw SyntaxError.
            { body: '<!DOCTYPE html>', status: 502, pattern: /status 502.*<!DOCTYPE html>/ },
        ]
        it.each(errorCases)(
            'throws a descriptive error for a non-JSON body (status $status)',
            async ({ body, status, pattern }) => {
                const res = new Response(body, { status })
                await expect(parseJsonResponse(res)).rejects.toThrow(pattern)
            }
        )
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
})
