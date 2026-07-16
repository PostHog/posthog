import { dropReadOnlyExceptions, dropRequestCancellationExceptions } from './exceptionAutocaptureFilters'

describe('exceptionAutocaptureFilters', () => {
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

    describe('dropRequestCancellationExceptions', () => {
        it('passes non-exception events through unchanged', () => {
            const event = { event: '$pageview', properties: { $current_url: '/foo' } }
            expect(dropRequestCancellationExceptions(event)).toBe(event)
        })

        it('drops $exception events raised by aborted requests', () => {
            // Cancelling an in-flight fetch rejects it with an `AbortError` DOMException —
            // e.g. the logs live-tail poll cancelled when a new poll starts.
            const event = {
                event: '$exception',
                properties: {
                    $exception_list: [{ type: 'AbortError', value: 'live tail request cancelled' }],
                },
            }
            expect(dropRequestCancellationExceptions(event)).toBeNull()
        })

        it('keeps genuine errors that are not cancellations', () => {
            const event = {
                event: '$exception',
                properties: {
                    $exception_list: [{ type: 'TimeoutError', value: 'signal timed out' }],
                },
            }
            expect(dropRequestCancellationExceptions(event)).toBe(event)
        })

        it('tolerates missing properties and returns null when handed null', () => {
            expect(dropRequestCancellationExceptions({ event: '$exception' })).toEqual({ event: '$exception' })
            expect(dropRequestCancellationExceptions(null)).toBeNull()
        })
    })
})
