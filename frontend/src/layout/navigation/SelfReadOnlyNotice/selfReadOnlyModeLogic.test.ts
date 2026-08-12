import { dropHandledAuthGateExceptions, dropReadOnlyExceptions } from './selfReadOnlyModeLogic'

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
