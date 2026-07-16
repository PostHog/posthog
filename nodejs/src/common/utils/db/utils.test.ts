import * as posthog from '../posthog'
import { timeoutGuard } from './utils'

describe('timeoutGuard()', () => {
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => {})
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        captureExceptionSpy.mockRestore()
    })

    // A bare string makes posthog-node synthesize a stack at the capture point, so every timeout
    // collapses into one error-tracking issue. Capturing a named Error is what keeps callsites apart.
    it('captures a named Error, not a bare string', () => {
        timeoutGuard('Redis call foo delayed', undefined, 100)
        jest.runOnlyPendingTimers()

        expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        const captured = captureExceptionSpy.mock.calls[0][0]
        expect(captured).toBeInstanceOf(Error)
        expect(captured.message).toBe('Redis call foo delayed')
    })

    it.each([
        { message: 'Redis call foo delayed', exceptionType: undefined, expectedName: 'Redis call foo delayed' },
        { message: 'Redis call foo delayed', exceptionType: 'Redis timeout: foo', expectedName: 'Redis timeout: foo' },
    ])(
        'names the exception "$expectedName" so distinct callsites group separately',
        ({ message, exceptionType, expectedName }) => {
            timeoutGuard(message, undefined, 100, true, undefined, exceptionType)
            jest.runOnlyPendingTimers()

            expect(captureExceptionSpy.mock.calls[0][0].name).toBe(expectedName)
        }
    )

    it('does not capture when sendException is false', () => {
        timeoutGuard('should not fire', undefined, 100, false)
        jest.runOnlyPendingTimers()

        expect(captureExceptionSpy).not.toHaveBeenCalled()
    })
})
