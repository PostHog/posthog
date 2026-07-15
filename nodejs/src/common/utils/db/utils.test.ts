import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { timeoutGuard } from './utils'

jest.mock('~/common/utils/logger')
jest.mock('~/common/utils/posthog')

const mockCaptureException = captureException as jest.MockedFunction<typeof captureException>

describe('timeoutGuard', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('captures with a per-message fingerprint so unrelated timeouts do not collapse into one issue', () => {
        clearTimeout(timeoutGuard('Redis call startup-ping delayed.', undefined, 1000))
        clearTimeout(timeoutGuard('cdpConsumer.publishBehavioralEvents timeout!', undefined, 1000))

        jest.advanceTimersByTime(1000)

        expect(mockCaptureException).toHaveBeenCalledTimes(2)
        expect(mockCaptureException.mock.calls[0]).toEqual([
            'Redis call startup-ping delayed.',
            expect.objectContaining({ fingerprint: 'plugin-server-timeout-guard:Redis call startup-ping delayed.' }),
        ])
        expect(mockCaptureException.mock.calls[1][1]).toEqual(
            expect.objectContaining({
                fingerprint: 'plugin-server-timeout-guard:cdpConsumer.publishBehavioralEvents timeout!',
            })
        )
        // Distinct fingerprints keep the two timeouts in separate error-tracking issues.
        expect(mockCaptureException.mock.calls[0][1]!.fingerprint).not.toEqual(
            mockCaptureException.mock.calls[1][1]!.fingerprint
        )
    })

    it('only logs (no capture) when sendException is false', () => {
        const reportMetric = jest.fn()
        clearTimeout(timeoutGuard('Redis call startup-ping delayed.', undefined, 1000, false, reportMetric))

        jest.advanceTimersByTime(1000)

        expect(logger.warn).toHaveBeenCalled()
        expect(reportMetric).toHaveBeenCalledTimes(1)
        expect(mockCaptureException).not.toHaveBeenCalled()
    })
})
