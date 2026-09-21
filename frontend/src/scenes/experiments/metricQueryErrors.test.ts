import { isCapacityError, isNoExposuresError } from './metricQueryErrors'

describe('metricQueryErrors', () => {
    describe('isNoExposuresError', () => {
        it('matches the no_data code the baseline-variant guard raises', () => {
            expect(isNoExposuresError({ code: 'no_data' })).toBe(true)
        })

        it('ignores other errors and missing input', () => {
            expect(isNoExposuresError({ code: 'no-results' })).toBe(false)
            expect(isNoExposuresError({ statusCode: 400 })).toBe(false)
            expect(isNoExposuresError(null)).toBe(false)
            expect(isNoExposuresError(undefined)).toBe(false)
        })
    })

    describe('isCapacityError', () => {
        // The two producers sit on opposite sides of the query runner and reach the browser
        // differently: the runner labels its catch with the shared code, while the per-team
        // concurrency limiter answers with a plain 429 before the runner starts.
        it('matches the runner capacity code', () => {
            expect(isCapacityError({ code: 'experiment_metric_rate_limited' })).toBe(true)
        })

        it('matches a 429 from the concurrency limiter', () => {
            expect(isCapacityError({ statusCode: 429 })).toBe(true)
        })

        it('does not match unrelated failures that must stay terminal', () => {
            expect(isCapacityError({ code: 'no_data' })).toBe(false)
            expect(isCapacityError({ statusCode: 500 })).toBe(false)
            expect(isCapacityError({ statusCode: 504 })).toBe(false)
            expect(isCapacityError(null)).toBe(false)
        })
    })
})
