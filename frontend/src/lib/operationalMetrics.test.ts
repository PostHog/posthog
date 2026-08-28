import posthog from 'posthog-js'

import { metricCount, metricHistogram } from 'lib/operationalMetrics'

describe('operationalMetrics', () => {
    // posthog-js is mocked app-wide in jest.setup.ts, including posthog.metrics.
    const metrics = posthog.metrics as unknown as { count: jest.Mock; histogram: jest.Mock }

    beforeEach(() => {
        jest.clearAllMocks()
        ;(posthog as { metrics?: unknown }).metrics = metrics
    })

    it('forwards counts with attributes in the options envelope', () => {
        metricCount('replay_test_total', 2, { kind: 'meta' })

        expect(metrics.count).toHaveBeenCalledWith('replay_test_total', 2, { attributes: { kind: 'meta' } })
    })

    it('omits the options envelope when there are no attributes', () => {
        metricCount('replay_test_total')

        expect(metrics.count).toHaveBeenCalledWith('replay_test_total', 1, undefined)
    })

    it('forwards histograms with unit and attributes', () => {
        metricHistogram('replay_test_ms', 187, 'ms', { source: 'list' })

        expect(metrics.histogram).toHaveBeenCalledWith('replay_test_ms', 187, {
            unit: 'ms',
            attributes: { source: 'list' },
        })
    })

    it('is a no-op when the SDK build has no metrics extension', () => {
        ;(posthog as { metrics?: unknown }).metrics = undefined

        expect(() => metricCount('replay_test_total')).not.toThrow()
        expect(() => metricHistogram('replay_test_ms', 1, 'ms')).not.toThrow()
    })
})
