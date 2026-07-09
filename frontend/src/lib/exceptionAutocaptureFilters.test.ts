import { ApiNetworkError } from 'lib/api-error'

import { addBeforeSendFilter, composedBeforeSend, dropNetworkErrors } from './exceptionAutocaptureFilters'

describe('exceptionAutocaptureFilters', () => {
    // Ties the filter to the error type: posthog-js serializes an error's `name` into
    // `$exception_list[].type`, so a rename on either side would silently let network
    // noise back into error tracking. Deriving the type from a real ApiNetworkError
    // keeps the two in lockstep.
    const networkErrorType = new ApiNetworkError('Load failed').name

    it('drops $exception events whose chain contains an ApiNetworkError', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: networkErrorType, value: 'Load failed' }] },
        }
        expect(dropNetworkErrors(event)).toBeNull()
    })

    it('drops wrapped errors where the ApiNetworkError lives deeper in the chain', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'Error', value: 'query failed' },
                    { type: networkErrorType, value: 'Load failed' },
                ],
            },
        }
        expect(dropNetworkErrors(event)).toBeNull()
    })

    it.each([
        ['non-exception event', { event: '$pageview', properties: { $current_url: '/foo' } }],
        [
            'unrelated exception',
            { event: '$exception', properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a fn' }] } },
        ],
        ['exception without a list', { event: '$exception' }],
    ])('passes %s through unchanged', (_label, event) => {
        expect(dropNetworkErrors(event)).toBe(event)
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropNetworkErrors(null)).toBeNull()
    })

    it('composes registered filters and stops sending once one drops the event', () => {
        const networkException = {
            event: '$exception',
            properties: { $exception_list: [{ type: networkErrorType, value: 'Load failed' }] },
        }
        const pageview = { event: '$pageview', properties: {} }

        // Nothing registered yet: everything passes through.
        expect(composedBeforeSend(networkException)).toBe(networkException)

        const dispose = addBeforeSendFilter(dropNetworkErrors)
        expect(composedBeforeSend(networkException)).toBeNull()
        expect(composedBeforeSend(pageview)).toBe(pageview)

        // Disposing removes the filter so the event flows again.
        dispose()
        expect(composedBeforeSend(networkException)).toBe(networkException)
    })
})
