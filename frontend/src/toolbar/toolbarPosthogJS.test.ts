import posthog from 'posthog-js'

import { captureToolbarException, classifyFetchError } from '~/toolbar/toolbarPosthogJS'

// posthog-js is mocked in jest.setup.ts. `posthog.init()` returns the same mock object,
// so `toolbarPosthogJS.captureException` and `posthog.captureException` reference the
// same jest.fn().
const captureExceptionMock = posthog.captureException as jest.Mock

describe('classifyFetchError', () => {
    it('classifies AbortError as timeout', () => {
        const err = new DOMException('aborted', 'AbortError')
        expect(classifyFetchError(err)).toBe('timeout')
    })

    it('classifies TypeError as network_or_cors (Safari "Load failed")', () => {
        expect(classifyFetchError(new TypeError('Load failed'))).toBe('network_or_cors')
        expect(classifyFetchError(new TypeError('Failed to fetch'))).toBe('network_or_cors')
    })

    it('classifies HTTP errors by message prefix', () => {
        expect(classifyFetchError(new Error('HTTP 500'))).toBe('http_error')
    })

    it('falls back to unknown for arbitrary errors', () => {
        expect(classifyFetchError(new Error('boom'))).toBe('unknown')
        expect(classifyFetchError('string error')).toBe('unknown')
        expect(classifyFetchError(null)).toBe('unknown')
    })
})

describe('captureToolbarException', () => {
    beforeEach(() => {
        captureExceptionMock.mockClear()
    })

    it('passes regular errors through with context tag', () => {
        const err = new Error('plain failure')
        captureToolbarException(err, 'flag_payload_parse', { flag_key: 'abc' })

        expect(captureExceptionMock).toHaveBeenCalledTimes(1)
        const [capturedError, props] = captureExceptionMock.mock.calls[0]
        expect(capturedError).toBe(err)
        expect(props).toMatchObject({ toolbar_context: 'flag_payload_parse', flag_key: 'abc' })
        expect(props).not.toHaveProperty('original_error_message')
    })

    it('skips $exception entirely for ui_host_check on opaque Safari fetch failures', () => {
        captureToolbarException(new TypeError('Load failed'), 'ui_host_check')
        captureToolbarException(new DOMException('aborted', 'AbortError'), 'ui_host_check')

        expect(captureExceptionMock).not.toHaveBeenCalled()
    })

    it('still captures ui_host_check failures when they are HTTP errors', () => {
        captureToolbarException(new Error('HTTP 502'), 'ui_host_check')

        expect(captureExceptionMock).toHaveBeenCalledTimes(1)
        expect(captureExceptionMock.mock.calls[0][1]).toMatchObject({
            toolbar_context: 'ui_host_check',
            error_type: 'http_error',
        })
    })

    it('rewraps opaque fetch failures with a context-stable message for non-ui-host contexts', () => {
        const original = new TypeError('Load failed')
        original.stack = 'TypeError: Load failed\n    at something'

        captureToolbarException(original, 'kea_loader', { reducer_key: 'r', action_key: 'a' })

        expect(captureExceptionMock).toHaveBeenCalledTimes(1)
        const [capturedError, props] = captureExceptionMock.mock.calls[0]

        expect(capturedError).not.toBe(original)
        expect(capturedError).toBeInstanceOf(Error)
        expect((capturedError as Error).message).toBe('toolbar fetch failed (network_or_cors) [kea_loader]')
        expect((capturedError as Error).stack).toBe(original.stack)
        expect(props).toMatchObject({
            toolbar_context: 'kea_loader',
            error_type: 'network_or_cors',
            original_error_message: 'Load failed',
            reducer_key: 'r',
            action_key: 'a',
        })
    })

    it('rewraps timeout (AbortError) failures with context-stable message', () => {
        const original = new DOMException('aborted', 'AbortError')
        captureToolbarException(original, 'token_refresh_retry')

        const [capturedError, props] = captureExceptionMock.mock.calls[0]
        expect((capturedError as Error).message).toBe('toolbar fetch failed (timeout) [token_refresh_retry]')
        expect(props).toMatchObject({
            toolbar_context: 'token_refresh_retry',
            error_type: 'timeout',
        })
    })

    it('lets additionalProperties override classifier-set error_type', () => {
        captureToolbarException(new Error('HTTP 500'), 'token_exchange', { error_type: 'custom' })

        const props = captureExceptionMock.mock.calls[0][1]
        expect(props.error_type).toBe('custom')
    })
})
