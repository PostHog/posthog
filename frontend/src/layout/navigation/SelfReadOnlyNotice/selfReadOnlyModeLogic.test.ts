import { NETWORK_ERROR_MESSAGES } from 'lib/api-error'

import {
    dropHandledAuthGateExceptions,
    dropInjectedScriptReferenceErrors,
    dropReadOnlyExceptions,
    dropUnactionableNetworkExceptions,
} from './selfReadOnlyModeLogic'

describe('dropReadOnlyExceptions', () => {
    it('passes non-exception events through unchanged', () => {
        const event = { event: '$pageview', properties: { $current_url: '/foo' } }
        expect(dropReadOnlyExceptions(event)).toBe(event)
    })

    it('passes $exception events without ReadOnlyModeError through', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'TypeError', value: 'x is not a function' }],
            },
        }
        expect(dropReadOnlyExceptions(event)).toBe(event)
    })

    it('drops $exception events whose top-level type is ReadOnlyModeError', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'ReadOnlyModeError', value: 'You are in read-only mode' }],
            },
        }
        expect(dropReadOnlyExceptions(event)).toBeNull()
    })

    it('drops wrapped errors where ReadOnlyModeError lives in the cause chain', () => {
        // posthog-js serializes `new Error('wrapper', { cause: readOnlyErr })`
        // by appending the cause to `$exception_list`. The filter walks the
        // whole list so wrappers do not slip through.
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'Error', value: 'reverseProxyCheckerLogic: query failed' },
                    { type: 'ReadOnlyModeError', value: 'You are in read-only mode' },
                ],
            },
        }
        expect(dropReadOnlyExceptions(event)).toBeNull()
    })

    it('tolerates missing properties and missing exception list', () => {
        expect(dropReadOnlyExceptions({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropReadOnlyExceptions({ event: '$exception', properties: {} })).toEqual({
            event: '$exception',
            properties: {},
        })
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropReadOnlyExceptions(null)).toBeNull()
    })
})

describe('dropHandledAuthGateExceptions', () => {
    it('passes real crashes through', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
        }
        expect(dropHandledAuthGateExceptions(event)).toBe(event)
    })

    // Each value is the message `ApiError` sets from the backend `detail` for a handled auth gate,
    // so a rejected request is expected control flow rather than a bug to report.
    it.each([
        ['2FA setup required'],
        ['2FA verification required'],
        ['This action requires you to be recently authenticated.'],
    ])('drops the handled auth-gate exception with message "%s"', (value) => {
        const event = { event: '$exception', properties: { $exception_list: [{ type: 'Error', value }] } }
        expect(dropHandledAuthGateExceptions(event)).toBeNull()
    })

    it('drops the gate even when it sits deeper in the exception list', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'Error', value: 'reverseProxyCheckerLogic: query failed' },
                    { type: 'Error', value: '2FA setup required' },
                ],
            },
        }
        expect(dropHandledAuthGateExceptions(event)).toBeNull()
    })

    it('tolerates missing properties and a missing exception list', () => {
        expect(dropHandledAuthGateExceptions({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropHandledAuthGateExceptions(null)).toBeNull()
    })
})

describe('dropUnactionableNetworkExceptions', () => {
    const exceptionWith = (value: string, type = 'NetworkError'): { event: string; properties: any } => ({
        event: '$exception',
        properties: { $exception_list: [{ type, value }] },
    })

    // The asymmetry is the whole point of the filter: the first two say something about the client's
    // situation, the third says a request failed while the user was online and staying put.
    it.each([
        ['device is offline', NETWORK_ERROR_MESSAGES.offline, true],
        ['page was closing', NETWORK_ERROR_MESSAGES.navigating, true],
        ['an unexplained connection failure', NETWORK_ERROR_MESSAGES.network, false],
    ])('given %s, drops the event: %s', (_desc, value, dropped) => {
        const event = exceptionWith(value)
        expect(dropUnactionableNetworkExceptions(event)).toBe(dropped ? null : event)
    })

    it('keeps an unrelated error that happens to carry a network message', () => {
        // Matching on the message alone would let any `Error` with this text be silenced
        const event = exceptionWith(NETWORK_ERROR_MESSAGES.offline, 'Error')
        expect(dropUnactionableNetworkExceptions(event)).toBe(event)
    })

    it('drops the failure even when it sits deeper in the exception list', () => {
        // posthog-js appends the wrapped cause, so `NetworkError` is not always first
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'Error', value: 'loadSavedHeatmaps failed' },
                    { type: 'NetworkError', value: NETWORK_ERROR_MESSAGES.navigating },
                ],
            },
        }
        expect(dropUnactionableNetworkExceptions(event)).toBeNull()
    })

    it('tolerates missing properties and a missing exception list', () => {
        expect(dropUnactionableNetworkExceptions({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropUnactionableNetworkExceptions(null)).toBeNull()
    })
})

describe('dropInjectedScriptReferenceErrors', () => {
    const injected = (value: string): { event: string; properties: any } => ({
        event: '$exception',
        properties: {
            $exception_list: [{ type: 'ReferenceError', value, mechanism: { type: 'generic', handled: false } }],
        },
    })

    // Real user-reported injected identifiers, in both the WebKit and the V8/SpiderMonkey wording.
    it.each([
        ["Can't find variable: pos"],
        ["Can't find variable: __firefox__"],
        ["Can't find variable: WeixinJSBridge"],
        ['zaloJSV2 is not defined'],
        ['chrome is not defined'],
        ['Rt is not defined'],
        ['ehrMain is not defined'],
    ])('drops the unhandled, frameless ReferenceError "%s"', (value) => {
        expect(dropInjectedScriptReferenceErrors(injected(value))).toBeNull()
    })

    it('keeps a ReferenceError from our own bundle, which carries a stack', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    {
                        type: 'ReferenceError',
                        value: 'foo is not defined',
                        mechanism: { type: 'generic', handled: false },
                        stacktrace: { frames: [{ source: 'https://us.posthog.com/static/chunk.js' }] },
                    },
                ],
            },
        }
        expect(dropInjectedScriptReferenceErrors(event)).toBe(event)
    })

    it('keeps a handled ReferenceError, which some code path already recovered from', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'ReferenceError', value: 'foo is not defined', mechanism: { handled: true } },
                ],
            },
        }
        expect(dropInjectedScriptReferenceErrors(event)).toBe(event)
    })

    it('keeps a non-ReferenceError that happens to match the message shape', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'TypeError', value: 'foo is not defined', mechanism: { handled: false } }],
            },
        }
        expect(dropInjectedScriptReferenceErrors(event)).toBe(event)
    })

    it('tolerates missing properties and a missing exception list', () => {
        expect(dropInjectedScriptReferenceErrors({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropInjectedScriptReferenceErrors(null)).toBeNull()
    })
})
