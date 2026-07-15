import { logger } from '~/common/utils/logger'
import * as posthog from '~/common/utils/posthog'

import { timeoutGuard } from './utils'

// utils.ts is loaded (via postgres.ts) by jest.setup.ts before any test-file jest.mock runs, so
// auto-mocking captureException can't rebind it. Spy on the live module export instead — utils.ts
// reads the property at call time, so the spy is observed regardless of load order.
describe('timeoutGuard', () => {
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers()
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => {})
    })

    afterEach(() => {
        jest.useRealTimers()
        captureExceptionSpy.mockRestore()
    })

    it('captures with a per-message fingerprint so unrelated timeouts do not collapse into one issue', () => {
        timeoutGuard('Redis call startup-ping delayed.', undefined, 1000)
        timeoutGuard('cdpConsumer.publishBehavioralEvents timeout!', undefined, 1000)

        jest.advanceTimersByTime(1000)

        expect(captureExceptionSpy).toHaveBeenCalledTimes(2)
        expect(captureExceptionSpy.mock.calls[0]).toEqual([
            'Redis call startup-ping delayed.',
            expect.objectContaining({ fingerprint: 'plugin-server-timeout-guard:Redis call startup-ping delayed.' }),
        ])
        expect(captureExceptionSpy.mock.calls[1][1]).toEqual(
            expect.objectContaining({
                fingerprint: 'plugin-server-timeout-guard:cdpConsumer.publishBehavioralEvents timeout!',
            })
        )
        // Distinct fingerprints keep the two timeouts in separate error-tracking issues.
        expect(captureExceptionSpy.mock.calls[0][1]?.fingerprint).not.toEqual(
            captureExceptionSpy.mock.calls[1][1]?.fingerprint
        )
    })

    it('only logs (no capture) when sendException is false', () => {
        const reportMetric = jest.fn()
        timeoutGuard('Redis call startup-ping delayed.', undefined, 1000, false, reportMetric)

        jest.advanceTimersByTime(1000)

        expect(logger.warn).toHaveBeenCalled()
        expect(reportMetric).toHaveBeenCalledTimes(1)
        expect(captureExceptionSpy).not.toHaveBeenCalled()
    })
})
