import { dayjs } from 'lib/dayjs'

import { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

import {
    EXPERIMENT_RESULTS_STALE_AFTER_MINUTES,
    EXPERIMENT_RESULTS_WARMING_UP_STALE_AFTER_MINUTES,
} from './constants'
import { experimentResultsAreStale } from './experimentLogic'

const resultRefreshedMinutesAgo = (minutes: number): CachedNewExperimentQueryResponse =>
    ({
        last_refresh: dayjs().subtract(minutes, 'minute').toISOString(),
    }) as CachedNewExperimentQueryResponse

describe('experimentResultsAreStale', () => {
    it('treats an empty result set as stale (no results yet — cheap to refresh)', () => {
        expect(experimentResultsAreStale([], EXPERIMENT_RESULTS_STALE_AFTER_MINUTES)).toBe(true)
    })

    it('treats results with no last_refresh as stale', () => {
        const results = [{} as CachedNewExperimentQueryResponse]
        expect(experimentResultsAreStale(results, EXPERIMENT_RESULTS_STALE_AFTER_MINUTES)).toBe(true)
    })

    it('is not stale when the freshest result is within the threshold', () => {
        const results = [resultRefreshedMinutesAgo(300), resultRefreshedMinutesAgo(120)]
        expect(experimentResultsAreStale(results, EXPERIMENT_RESULTS_STALE_AFTER_MINUTES)).toBe(false)
    })

    it('is stale when every result is older than the threshold', () => {
        const results = [resultRefreshedMinutesAgo(200), resultRefreshedMinutesAgo(600)]
        expect(experimentResultsAreStale(results, EXPERIMENT_RESULTS_STALE_AFTER_MINUTES)).toBe(true)
    })

    it('uses the freshest result across primary and secondary metrics', () => {
        // One metric is stale, but another was refreshed recently — overall not stale.
        const results = [resultRefreshedMinutesAgo(600), resultRefreshedMinutesAgo(5)]
        expect(experimentResultsAreStale(results, EXPERIMENT_RESULTS_STALE_AFTER_MINUTES)).toBe(false)
    })

    it('ignores sparse holes left by metrics that returned no baseline', () => {
        const results = new Array(3) as CachedNewExperimentQueryResponse[]
        results[1] = resultRefreshedMinutesAgo(5)
        expect(experimentResultsAreStale(results, EXPERIMENT_RESULTS_STALE_AFTER_MINUTES)).toBe(false)
    })

    describe('warming-up window (until exposures are seen)', () => {
        it('refreshes a result older than a minute', () => {
            const results = [resultRefreshedMinutesAgo(2)]
            expect(experimentResultsAreStale(results, EXPERIMENT_RESULTS_WARMING_UP_STALE_AFTER_MINUTES)).toBe(true)
        })

        it('does not refresh a result from within the last minute', () => {
            const results = [resultRefreshedMinutesAgo(0.5)]
            expect(experimentResultsAreStale(results, EXPERIMENT_RESULTS_WARMING_UP_STALE_AFTER_MINUTES)).toBe(false)
        })
    })
})
