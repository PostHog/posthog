import { dropAbortErrors, dropReadOnlyExceptions } from './exceptionAutocaptureFilters'

describe('exceptionAutocaptureFilters', () => {
    describe('dropAbortErrors', () => {
        it('passes non-exception events through unchanged', () => {
            const event = { event: '$pageview', properties: { $current_url: '/foo' } }
            expect(dropAbortErrors(event)).toBe(event)
        })

        it('passes $exception events without an abort through', () => {
            const event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
            }
            expect(dropAbortErrors(event)).toBe(event)
        })

        // The DOMException shape (`type: 'DOMException', value: 'AbortError: ...'`) is what
        // posthog-js's autocapture produces for `abort(new DOMException(msg, 'AbortError'))` —
        // the actual fingerprint that flooded error tracking. The plain-Error shape
        // (`type: 'AbortError'`) covers errors whose `name` is AbortError directly.
        it.each([
            ['DOMException shape', { type: 'DOMException', value: 'AbortError: new query started' }],
            ['plain Error shape', { type: 'AbortError', value: 'new query started' }],
        ])('drops $exception events for the abort %s', (_name, entry) => {
            const event = { event: '$exception', properties: { $exception_list: [entry] } }
            expect(dropAbortErrors(event)).toBeNull()
        })

        it('does not drop unrelated errors that merely mention abort mid-value', () => {
            const event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'Error', value: 'failed to AbortError parsing' }] },
            }
            expect(dropAbortErrors(event)).toBe(event)
        })

        it('tolerates missing properties and missing exception list', () => {
            expect(dropAbortErrors({ event: '$exception' })).toEqual({ event: '$exception' })
        })

        it('returns null when handed null (matching posthog-js before_send contract)', () => {
            expect(dropAbortErrors(null)).toBeNull()
        })
    })

    describe('dropReadOnlyExceptions', () => {
        it('passes non-exception events through unchanged', () => {
            const event = { event: '$pageview', properties: { $current_url: '/foo' } }
            expect(dropReadOnlyExceptions(event)).toBe(event)
        })

        it('passes $exception events without ReadOnlyModeError through', () => {
            const event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
            }
            expect(dropReadOnlyExceptions(event)).toBe(event)
        })

        it('drops $exception events whose top-level type is ReadOnlyModeError', () => {
            const event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'ReadOnlyModeError', value: 'You are in read-only mode' }] },
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
})
