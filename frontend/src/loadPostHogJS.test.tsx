import { type CaptureResult } from 'posthog-js'

import { filterFirefoxInjectedExceptions } from './loadPostHogJS'

describe('filterFirefoxInjectedExceptions', () => {
    const makeEvent = (event: string, exceptionValues: unknown): CaptureResult =>
        ({
            uuid: 'test-uuid',
            event,
            properties: { $exception_values: exceptionValues },
        }) as CaptureResult

    it.each([
        "undefined is not an object (evaluating 'window.__firefox__.reader')",
        "undefined is not an object (evaluating 'window.__firefox__.playlistLongPressed_123')",
    ])('drops Firefox for iOS injected exceptions: %s', (message) => {
        expect(filterFirefoxInjectedExceptions(makeEvent('$exception', [message]))).toBeNull()
    })

    it('preserves application exceptions', () => {
        const event = makeEvent('$exception', ['undefined is not an object'])

        expect(filterFirefoxInjectedExceptions(event)).toBe(event)
    })

    it('preserves non-exception events containing the Firefox bridge name', () => {
        const event = makeEvent('custom event', ['window.__firefox__.reader'])

        expect(filterFirefoxInjectedExceptions(event)).toBe(event)
    })
})
