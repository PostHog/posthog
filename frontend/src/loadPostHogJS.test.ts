import posthog, { BeforeSendFn, CaptureResult } from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { NETWORK_ERROR_MESSAGES } from 'lib/api-error'

import { isInDeferredInitSample, loadPostHogJS } from './loadPostHogJS'

function networkException(message: string): CaptureResult {
    return {
        uuid: 'test-uuid',
        event: '$exception',
        properties: { $exception_list: [{ type: 'NetworkError', value: message }] },
    }
}

function runBeforeSend(event: CaptureResult): CaptureResult | null {
    const { before_send: beforeSend } = (posthog.init as jest.Mock).mock.calls[0][1]
    return (beforeSend as BeforeSendFn[]).reduce<CaptureResult | null>(
        (survivor, filter) => (survivor ? filter(survivor) : null),
        event
    )
}

describe('loadPostHogJS', () => {
    describe('isInDeferredInitSample', () => {
        it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
            'keeps the posthog-js sampling verdict for session %p',
            (sessionId) => {
                expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
            }
        )
    })

    describe('before_send', () => {
        beforeEach(() => {
            ;(posthog.init as jest.Mock).mockClear()
            ;(posthog.get_session_id as jest.Mock).mockReturnValue('session-one')
            window.JS_POSTHOG_API_KEY = 'test-key'
        })

        afterEach(() => {
            delete window.JS_POSTHOG_API_KEY
        })

        // Guards the wiring, not the filter: with no `before_send` chain here, every offline
        // browser files an error tracking issue of its own.
        it.each([
            ['the offline exception', NETWORK_ERROR_MESSAGES.offline, true],
            ['the page-closing exception', NETWORK_ERROR_MESSAGES.navigating, true],
            ['the residual network exception', NETWORK_ERROR_MESSAGES.network, false],
        ])('decides whether to drop %s before it leaves the browser', (_, message, dropped) => {
            loadPostHogJS()

            const event = networkException(message)

            expect(runBeforeSend(event)).toBe(dropped ? null : event)
        })

        it('still runs a caller-supplied hook on whatever survives', () => {
            const redact = jest.fn((event: CaptureResult | null) => event)

            loadPostHogJS({ beforeSend: redact })

            expect(runBeforeSend(networkException(NETWORK_ERROR_MESSAGES.offline))).toBeNull()
            expect(redact).not.toHaveBeenCalled()

            expect(runBeforeSend(networkException(NETWORK_ERROR_MESSAGES.network))).not.toBeNull()
            expect(redact).toHaveBeenCalledTimes(1)
        })
    })
})
