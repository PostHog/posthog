import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { isInDeferredInitSample } from './loadPostHogJS'

describe('isInDeferredInitSample', () => {
    it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
        'keeps the posthog-js sampling verdict for session %p',
        (sessionId) => {
            expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
        }
    )
})
