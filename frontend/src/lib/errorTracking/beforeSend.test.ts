import { composedBeforeSend, dropCancellationExceptions, registerBeforeSendFilter } from './beforeSend'

describe('before_send filters', () => {
    const abortEvent = {
        event: '$exception',
        properties: { $exception_list: [{ type: 'AbortError', value: 'signal is aborted without reason' }] },
    }

    it('drops $exception events for aborted (cancelled) requests', () => {
        expect(dropCancellationExceptions(abortEvent as any)).toBeNull()
    })

    it('passes through $exception events that are not AbortErrors', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
        }
        expect(dropCancellationExceptions(event as any)).toBe(event)
    })

    it('passes non-exception events and null through unchanged', () => {
        const pageview = { event: '$pageview', properties: {} }
        expect(dropCancellationExceptions(pageview as any)).toBe(pageview)
        expect(dropCancellationExceptions(null as any)).toBeNull()
    })

    it('drops AbortError exceptions via composedBeforeSend even with no registered filters', () => {
        expect(composedBeforeSend(abortEvent as any)).toBeNull()
    })

    it('runs registered filters in order and stops once one drops the event', () => {
        const passthrough = { event: '$exception', properties: { $exception_list: [{ type: 'TypeError' }] } }
        const secondFilter = jest.fn((e) => e)
        const unregisterDrop = registerBeforeSendFilter(() => null)
        const unregisterSecond = registerBeforeSendFilter(secondFilter)
        try {
            expect(composedBeforeSend(passthrough as any)).toBeNull()
            // a filter that returned null short-circuits, so later filters never run
            expect(secondFilter).not.toHaveBeenCalled()
        } finally {
            unregisterDrop()
            unregisterSecond()
        }
    })

    it('unregister removes a filter from the chain', () => {
        const event = { event: '$exception', properties: { $exception_list: [{ type: 'TypeError' }] } }
        const unregister = registerBeforeSendFilter(() => null)
        unregister()
        expect(composedBeforeSend(event as any)).toBe(event)
    })
})
