import { CaptureResult } from 'posthog-js'

import { NETWORK_ERROR_MESSAGES } from 'lib/api-error'

import {
    dropHandledAuthGateExceptions,
    dropInjectedScriptReferenceErrors,
    dropScopeNotFoundExceptions,
    dropUnactionableNetworkExceptions,
} from './exceptionFilters'

const exceptionEvent = (exceptions: Record<string, unknown>[], event = '$exception'): CaptureResult => ({
    uuid: 'example-uuid',
    event,
    properties: { $exception_list: exceptions },
})

const unhandledReferenceError = (value: string, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
    type: 'ReferenceError',
    value,
    mechanism: { type: 'generic', handled: false },
    ...extra,
})

describe('exceptionFilters', () => {
    it.each([
        ['dropScopeNotFoundExceptions', dropScopeNotFoundExceptions],
        ['dropHandledAuthGateExceptions', dropHandledAuthGateExceptions],
        ['dropUnactionableNetworkExceptions', dropUnactionableNetworkExceptions],
        ['dropInjectedScriptReferenceErrors', dropInjectedScriptReferenceErrors],
    ])('%s passes through non-exception events and exceptions with no list', (_, filter) => {
        const pageview = exceptionEvent([{ type: 'Error', value: 'Project not found.' }], '$pageview')
        const bare: CaptureResult = { uuid: 'example-uuid', event: '$exception', properties: {} }

        expect(filter(pageview)).toBe(pageview)
        expect(filter(bare)).toBe(bare)
    })

    describe('dropScopeNotFoundExceptions', () => {
        it.each([
            ['an uncaught dead-project rejection', ['Project not found.'], false],
            ['an uncaught dead-organization rejection', ['Organization not found.'], false],
            ['a dead-scope rejection wrapped as a cause', ['Failed to load', 'Project not found.'], false],
            ['an unrelated exception', ['Not found.'], true],
        ])('handles %s', (_, values, kept) => {
            const event = exceptionEvent(values.map((value) => ({ type: 'Error', value })))

            expect(dropScopeNotFoundExceptions(event)).toBe(kept ? event : null)
        })
    })

    describe('dropHandledAuthGateExceptions', () => {
        // Each value is the message `ApiError` sets from the backend `detail` for a handled auth gate.
        it.each([
            ['2FA setup required', [{ type: 'Error', value: '2FA setup required' }], false],
            ['2FA verification required', [{ type: 'Error', value: '2FA verification required' }], false],
            [
                'a re-auth prompt',
                [{ type: 'Error', value: 'This action requires you to be recently authenticated.' }],
                false,
            ],
            [
                'a gate wrapped as a cause',
                [
                    { type: 'Error', value: 'reverseProxyCheckerLogic: query failed' },
                    { type: 'Error', value: '2FA setup required' },
                ],
                false,
            ],
            ['a real crash', [{ type: 'TypeError', value: 'x is not a function' }], true],
        ])('handles %s', (_, exceptions, kept) => {
            const event = exceptionEvent(exceptions)

            expect(dropHandledAuthGateExceptions(event)).toBe(kept ? event : null)
        })
    })

    describe('dropUnactionableNetworkExceptions', () => {
        // The asymmetry is the point of the filter: offline and navigating describe the client's
        // situation, while `network` means a request failed while the user was online and staying put.
        it.each([
            ['a request while offline', [{ type: 'NetworkError', value: NETWORK_ERROR_MESSAGES.offline }], false],
            [
                'a request while the page was closing',
                [{ type: 'NetworkError', value: NETWORK_ERROR_MESSAGES.navigating }],
                false,
            ],
            [
                'a failure wrapped as a cause',
                [
                    { type: 'Error', value: 'loadSavedHeatmaps failed' },
                    { type: 'NetworkError', value: NETWORK_ERROR_MESSAGES.navigating },
                ],
                false,
            ],
            [
                'an unexplained connection failure',
                [{ type: 'NetworkError', value: NETWORK_ERROR_MESSAGES.network }],
                true,
            ],
            [
                'an unrelated error that carries a network message',
                [{ type: 'Error', value: NETWORK_ERROR_MESSAGES.offline }],
                true,
            ],
        ])('handles %s', (_, exceptions, kept) => {
            const event = exceptionEvent(exceptions)

            expect(dropUnactionableNetworkExceptions(event)).toBe(kept ? event : null)
        })
    })

    describe('dropInjectedScriptReferenceErrors', () => {
        it.each([
            [
                "the WebKit wording, Can't find variable: WeixinJSBridge",
                [unhandledReferenceError("Can't find variable: WeixinJSBridge")],
                false,
            ],
            ['the V8 wording, zaloJSV2 is not defined', [unhandledReferenceError('zaloJSV2 is not defined')], false],
            [
                'a ReferenceError from our own bundle, which carries a stack',
                [
                    unhandledReferenceError('foo is not defined', {
                        stacktrace: { frames: [{ filename: 'https://example.com/static/chunk.js' }] },
                    }),
                ],
                true,
            ],
            ...['webkit-masked-url://', 'chrome-extension://', 'moz-extension://', 'safari-web-extension://'].map(
                (scheme): [string, Record<string, unknown>[], boolean] => [
                    `an extension crash frame using ${scheme}`,
                    [
                        unhandledReferenceError('extensionHook is not defined', {
                            stacktrace: {
                                frames: [
                                    { filename: 'https://example.com/page' },
                                    { filename: `${scheme}example/script.js`, in_app: false },
                                ],
                            },
                        }),
                    ],
                    false,
                ]
            ),
            [
                'an extension crash frame with WebKit wording',
                [
                    unhandledReferenceError("Can't find variable: extensionHook", {
                        stacktrace: { frames: [{ filename: 'webkit-masked-url://example/script.js', in_app: false }] },
                    }),
                ],
                false,
            ],
            [
                'an app crash called by an extension',
                [
                    unhandledReferenceError('foo is not defined', {
                        stacktrace: {
                            frames: [
                                { filename: 'chrome-extension://example/script.js', in_app: false },
                                { filename: 'https://example.com/static/chunk.js', in_app: true },
                            ],
                        },
                    }),
                ],
                true,
            ],
            [
                'a handled extension error',
                [
                    unhandledReferenceError('extensionHook is not defined', {
                        mechanism: { handled: true },
                        stacktrace: { frames: [{ filename: 'chrome-extension://example/script.js' }] },
                    }),
                ],
                true,
            ],
            [
                'an extension ReferenceError with a different message',
                [
                    unhandledReferenceError('Cannot access variable before initialization', {
                        stacktrace: { frames: [{ filename: 'moz-extension://example/script.js' }] },
                    }),
                ],
                true,
            ],
            [
                'a wrapped extension error with an app stack',
                [
                    {
                        type: 'Error',
                        mechanism: { handled: false },
                        stacktrace: { frames: [{ filename: 'https://example.com/static/chunk.js' }] },
                    },
                    unhandledReferenceError('extensionHook is not defined', {
                        stacktrace: { frames: [{ filename: 'chrome-extension://example/script.js' }] },
                    }),
                ],
                true,
            ],
            [
                'a handled ReferenceError',
                [{ type: 'ReferenceError', value: 'foo is not defined', mechanism: { handled: true } }],
                true,
            ],
            [
                'a non-ReferenceError with the same message shape',
                [{ type: 'TypeError', value: 'foo is not defined', mechanism: { handled: false } }],
                true,
            ],
        ])('handles %s', (_, exceptions, kept) => {
            const event = exceptionEvent(exceptions)

            expect(dropInjectedScriptReferenceErrors(event)).toBe(kept ? event : null)
        })
    })
})
