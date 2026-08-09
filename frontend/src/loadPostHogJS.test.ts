import { CaptureResult } from 'posthog-js'

import { dropResizeObserverLoopErrors } from './loadPostHogJS'

describe('dropResizeObserverLoopErrors', () => {
    const exceptionEvent = (value: string): CaptureResult =>
        ({
            event: '$exception',
            properties: { $exception_list: [{ type: 'Error', value }] },
        }) as unknown as CaptureResult

    it('drops the benign ResizeObserver loop exception', () => {
        expect(
            dropResizeObserverLoopErrors(exceptionEvent('ResizeObserver loop completed with undelivered notifications'))
        ).toBeNull()
        expect(dropResizeObserverLoopErrors(exceptionEvent('ResizeObserver loop limit exceeded'))).toBeNull()
    })

    it('keeps other exceptions and other events', () => {
        const realException = exceptionEvent('TypeError: cannot read property')
        expect(dropResizeObserverLoopErrors(realException)).toBe(realException)

        const pageview = { event: '$pageview', properties: {} } as CaptureResult
        expect(dropResizeObserverLoopErrors(pageview)).toBe(pageview)

        expect(dropResizeObserverLoopErrors(null)).toBeNull()
    })
})
