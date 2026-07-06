import { dayjs } from 'lib/dayjs'

import { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

import { NEW_EXPERIMENT_FORCE_REFRESH_AFTER_MINUTES } from './constants'
import { experimentResultsAreStale } from './experimentLogic'

const THRESHOLD = NEW_EXPERIMENT_FORCE_REFRESH_AFTER_MINUTES

const resultRefreshedMinutesAgo = (minutes: number): CachedNewExperimentQueryResponse =>
    ({
        last_refresh: dayjs().subtract(minutes, 'minute').toISOString(),
    }) as CachedNewExperimentQueryResponse

describe('experimentResultsAreStale', () => {
    it('treats an empty result set as stale (no results yet — cheap to refresh)', () => {
        expect(experimentResultsAreStale([], THRESHOLD)).toBe(true)
    })

    it('treats results with no last_refresh as stale', () => {
        expect(experimentResultsAreStale([{} as CachedNewExperimentQueryResponse], THRESHOLD)).toBe(true)
    })

    it('is not stale when the freshest result is within the threshold', () => {
        const results = [resultRefreshedMinutesAgo(THRESHOLD * 5), resultRefreshedMinutesAgo(THRESHOLD / 2)]
        expect(experimentResultsAreStale(results, THRESHOLD)).toBe(false)
    })

    it('is stale when every result is older than the threshold', () => {
        const results = [resultRefreshedMinutesAgo(THRESHOLD * 2), resultRefreshedMinutesAgo(THRESHOLD * 5)]
        expect(experimentResultsAreStale(results, THRESHOLD)).toBe(true)
    })

    it('uses the freshest result across primary and secondary metrics', () => {
        // One metric is stale, but another was refreshed recently — overall not stale.
        const results = [resultRefreshedMinutesAgo(THRESHOLD * 10), resultRefreshedMinutesAgo(THRESHOLD / 2)]
        expect(experimentResultsAreStale(results, THRESHOLD)).toBe(false)
    })

    it('ignores sparse holes left by metrics that returned no baseline', () => {
        const results = new Array(3) as (CachedNewExperimentQueryResponse | undefined)[]
        results[1] = resultRefreshedMinutesAgo(THRESHOLD / 2)
        expect(experimentResultsAreStale(results, THRESHOLD)).toBe(false)
    })
})
