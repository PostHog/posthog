import { generatePKCE, InsecureContextError, joinWithUiHost, slashDotDataAttrUnescape } from './utils'

describe('utils', () => {
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

    describe('generatePKCE', () => {
        const originalCrypto = global.crypto

        afterEach(() => {
            Object.defineProperty(global, 'crypto', { value: originalCrypto, configurable: true })
        })

        it('throws InsecureContextError when crypto.subtle is undefined', async () => {
            // Simulates loading the toolbar on a non-secure HTTP host (e.g. http://vm-docker-spb6:3535),
            // where the browser does not expose SubtleCrypto. Pre-fix this surfaced as an opaque
            // TypeError reading .digest of undefined.
            Object.defineProperty(global, 'crypto', {
                value: { getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto) },
                configurable: true,
            })
            await expect(generatePKCE()).rejects.toThrow(InsecureContextError)
        })

        it('throws InsecureContextError when crypto.subtle.digest is not a function', async () => {
            Object.defineProperty(global, 'crypto', {
                value: {
                    getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto),
                    subtle: { digest: undefined },
                },
                configurable: true,
            })
            await expect(generatePKCE()).rejects.toThrow(InsecureContextError)
        })

        it('produces a verifier and challenge when crypto.subtle is available', async () => {
            // JSDOM doesn't expose SubtleCrypto by default, so stub a digest implementation.
            Object.defineProperty(global, 'crypto', {
                value: {
                    getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto),
                    subtle: {
                        digest: jest.fn(async () => new Uint8Array(32).fill(0xab).buffer),
                    },
                },
                configurable: true,
            })
            const { verifier, challenge } = await generatePKCE()
            expect(verifier).toMatch(/^[A-Za-z0-9_-]+$/)
            expect(challenge).toMatch(/^[A-Za-z0-9_-]+$/)
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
