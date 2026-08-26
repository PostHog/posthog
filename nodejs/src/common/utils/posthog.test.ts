import { sampleException } from '~/common/utils/posthog'

describe('sampleException', () => {
    it('reports a burst then throttles a crash loop of one signature', () => {
        const now = 1_000_000
        const error = new Error('unique crash loop A')

        // The burst of 5 is reported.
        for (let i = 0; i < 5; i++) {
            expect(sampleException(error, now)).toEqual({ capture: true, suppressed: 0 })
        }

        // Further identical errors are suppressed and counted, not reported.
        expect(sampleException(error, now)).toEqual({ capture: false, suppressed: 0 })
        expect(sampleException(error, now)).toEqual({ capture: false, suppressed: 0 })

        // Once a token replenishes, the next sample carries the suppressed count.
        expect(sampleException(error, now + 60_000)).toEqual({ capture: true, suppressed: 2 })

        // The count resets after it is reported.
        expect(sampleException(error, now + 120_000)).toEqual({ capture: true, suppressed: 0 })
    })

    it('collapses variable message parts to one signature', () => {
        const now = 2_000_000

        // Drain the burst with one endpoint address.
        for (let i = 0; i < 5; i++) {
            sampleException(new Error('[unavailable] connect ECONNREFUSED 10.0.0.1:50052'), now)
        }

        // A different address maps to the same signature, so it is throttled too.
        expect(sampleException(new Error('[unavailable] connect ECONNREFUSED 10.0.0.2:50053'), now)).toEqual({
            capture: false,
            suppressed: 0,
        })
    })
})
