import { dayjs } from 'lib/dayjs'

import { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

import { NEW_EXPERIMENT_FORCE_REFRESH_AFTER_MINUTES } from './constants'
import { experimentResultsAreStale } from './experimentLogic'

const resultRefreshedMinutesAgo = (minutes: number): CachedNewExperimentQueryResponse =>
    ({
        last_refresh: dayjs().subtract(minutes, 'minute').toISOString(),
    }) as CachedNewExperimentQueryResponse

describe('experimentResultsAreStale', () => {
    it('treats an empty result set as stale (no results yet — cheap to refresh)', () => {
        expect(experimentResultsAreStale([], 60)).toBe(true)
    })

    it('treats results with no last_refresh as stale', () => {
        expect(experimentResultsAreStale([{} as CachedNewExperimentQueryResponse], 60)).toBe(true)
    })

    it('is not stale when the freshest result is within the threshold', () => {
        expect(experimentResultsAreStale([resultRefreshedMinutesAgo(120), resultRefreshedMinutesAgo(30)], 60)).toBe(
            false
        )
    })

    it('is stale when every result is older than the threshold', () => {
        expect(experimentResultsAreStale([resultRefreshedMinutesAgo(90), resultRefreshedMinutesAgo(200)], 60)).toBe(
            true
        )
    })

    it('uses the freshest result across primary and secondary metrics', () => {
        // One metric is stale, but another was refreshed recently — overall not stale.
        expect(experimentResultsAreStale([resultRefreshedMinutesAgo(600), resultRefreshedMinutesAgo(5)], 60)).toBe(
            false
        )
    })

    it('ignores sparse holes left by metrics that returned no baseline', () => {
        const results = new Array(3) as (CachedNewExperimentQueryResponse | undefined)[]
        results[1] = resultRefreshedMinutesAgo(5)
        expect(experimentResultsAreStale(results, 60)).toBe(false)
    })

    describe('warming-up window', () => {
        it('refreshes results older than the warming-up window', () => {
            const results = [resultRefreshedMinutesAgo(2)]
            expect(experimentResultsAreStale(results, NEW_EXPERIMENT_FORCE_REFRESH_AFTER_MINUTES)).toBe(true)
        })

        it('does not refresh results from within the warming-up window', () => {
            const results = [resultRefreshedMinutesAgo(0.5)]
            expect(experimentResultsAreStale(results, NEW_EXPERIMENT_FORCE_REFRESH_AFTER_MINUTES)).toBe(false)
        })
    })
})
