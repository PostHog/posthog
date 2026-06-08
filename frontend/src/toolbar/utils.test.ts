import { webcrypto } from 'node:crypto'

import {
    asNonEmptyString,
    CryptoUnsupportedError,
    generatePKCE,
    joinWithUiHost,
    slashDotDataAttrUnescape,
} from './utils'

describe('utils', () => {
    describe('generatePKCE', () => {
        const originalSecureCtx = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
        const originalCrypto = Object.getOwnPropertyDescriptor(window, 'crypto')

        const setSecureContext = (value: boolean): void => {
            Object.defineProperty(window, 'isSecureContext', { value, configurable: true, writable: true })
        }

        const setCrypto = (value: unknown): void => {
            Object.defineProperty(window, 'crypto', { value, configurable: true, writable: true })
        }

        afterEach(() => {
            if (originalSecureCtx) {
                Object.defineProperty(window, 'isSecureContext', originalSecureCtx)
            }
            if (originalCrypto) {
                Object.defineProperty(window, 'crypto', originalCrypto)
            }
        })

        it('returns a verifier and challenge in a secure context with usable SubtleCrypto', async () => {
            setSecureContext(true)
            setCrypto(webcrypto)
            const { verifier, challenge } = await generatePKCE()
            expect(typeof verifier).toBe('string')
            expect(verifier.length).toBeGreaterThan(0)
            expect(typeof challenge).toBe('string')
            expect(challenge.length).toBeGreaterThan(0)
            // base64url: no padding or non-url-safe characters
            expect(verifier).not.toMatch(/[+/=]/)
            expect(challenge).not.toMatch(/[+/=]/)
        })

        const unsupportedCases: Array<{ name: string; secureContext: boolean; crypto: unknown }> = [
            { name: 'non-secure context', secureContext: false, crypto: webcrypto },
            // Secure contexts gate `crypto.subtle`; some runtimes expose `crypto` without it.
            {
                name: 'crypto.subtle is undefined',
                secureContext: true,
                crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
            },
            // A partial WebCrypto shim (e.g. React Native Web) where digest is missing.
            {
                name: 'SubtleCrypto.digest is not callable',
                secureContext: true,
                crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto), subtle: {} },
            },
        ]
        it.each(unsupportedCases)('throws CryptoUnsupportedError when $name', async ({ secureContext, crypto }) => {
            setSecureContext(secureContext)
            setCrypto(crypto)
            await expect(generatePKCE()).rejects.toBeInstanceOf(CryptoUnsupportedError)
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
})
