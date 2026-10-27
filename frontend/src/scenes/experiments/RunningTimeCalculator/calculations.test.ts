import { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

import { calculateCurrentExposures, calculateDaysElapsed, calculateExposureRate } from './calculations'

// The sample-size / variance math is verified in the backend
// (products/experiments/backend/test/test_running_time_calculator.py). These tests
// cover the client-side helpers that read live experiment state.
describe('running time calculations', () => {
    describe('calculateCurrentExposures', () => {
        it('sums baseline and variant sample counts', () => {
            const results = {
                baseline: { number_of_samples: 1000 },
                variant_results: [{ number_of_samples: 900 }, { number_of_samples: 1100 }],
            } as CachedNewExperimentQueryResponse
            expect(calculateCurrentExposures(results)).toBe(3000)
        })

        it('returns null without results', () => {
            expect(calculateCurrentExposures(null)).toBeNull()
        })
    })

    describe('calculateExposureRate', () => {
        it('returns exposures per day', () => {
            expect(calculateExposureRate(1000, 10)).toBe(100)
        })

        it('returns null below the minimum elapsed window', () => {
            expect(calculateExposureRate(1000, 0.05)).toBeNull()
        })

        it('returns null without exposures', () => {
            expect(calculateExposureRate(null, 10)).toBeNull()
        })
    })

    describe('calculateDaysElapsed', () => {
        it('returns null without a start date', () => {
            expect(calculateDaysElapsed(null)).toBeNull()
        })

        it('returns a positive number for a past start date', () => {
            const elapsed = calculateDaysElapsed('2020-01-01')
            expect(elapsed).not.toBeNull()
            expect(elapsed!).toBeGreaterThan(0)
        })
    })
})
