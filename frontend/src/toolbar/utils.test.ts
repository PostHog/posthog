import { asNonEmptyString, joinWithUiHost, slashDotDataAttrUnescape, toolbarStylesUrl } from './utils'

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

    describe('toolbarStylesUrl', () => {
        // 1780595730000 floors to 1780595700000 at 5-minute granularity.
        const nowMs = 1780595730000
        const cacheBuster = 1780595700000

        const testCases: Array<{
            name: string
            publicPath: string
            scriptSrc: string | null
            apiHost: string
            expected: string
        }> = [
            {
                name: 'baked-in public path wins and skips the cache-buster',
                publicPath: 'https://us-assets.i.posthog.com/static/1.358.0/',
                scriptSrc: 'https://www.example.com/proxy/static/toolbar.js?t=1',
                apiHost: 'https://www.example.com',
                expected: 'https://us-assets.i.posthog.com/static/1.358.0/toolbar.css',
            },
            {
                name: 'derives from the script src behind a reverse proxy',
                publicPath: '',
                scriptSrc: 'https://www.mappedin.com/mappedin-ingest/static/toolbar.js?t=1780595700000',
                apiHost: 'https://www.mappedin.com',
                expected: `https://www.mappedin.com/mappedin-ingest/static/toolbar.css?t=${cacheBuster}`,
            },
            {
                name: 'script src takes precedence over apiHost when both resolve',
                publicPath: '',
                scriptSrc: 'https://www.example.com/ingest/static/toolbar.js',
                apiHost: 'https://www.example.com',
                expected: `https://www.example.com/ingest/static/toolbar.css?t=${cacheBuster}`,
            },
            {
                name: 'falls back to apiHost/static when no script src is available',
                publicPath: '',
                scriptSrc: null,
                apiHost: 'https://www.example.com',
                expected: `https://www.example.com/static/toolbar.css?t=${cacheBuster}`,
            },
            {
                name: 'falls back to apiHost when the script src is not a valid URL',
                publicPath: '',
                scriptSrc: 'not-a-url',
                apiHost: 'https://www.example.com',
                expected: `https://www.example.com/static/toolbar.css?t=${cacheBuster}`,
            },
            {
                name: 'preserves an apiHost path prefix in the fallback',
                publicPath: '',
                scriptSrc: null,
                apiHost: 'https://www.example.com/ingest',
                expected: `https://www.example.com/ingest/static/toolbar.css?t=${cacheBuster}`,
            },
        ]

        it.each(testCases)('$name', ({ publicPath, scriptSrc, apiHost, expected }) => {
            expect(toolbarStylesUrl(publicPath, scriptSrc, apiHost, nowMs)).toBe(expected)
        })
    })
})
