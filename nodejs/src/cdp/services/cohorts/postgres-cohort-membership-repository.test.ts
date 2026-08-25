import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { resetBehavioralCohortsDatabase } from '~/tests/helpers/sql'

import { insertCohortMemberships } from '../../_tests/fixtures'
import {
    CohortMembershipLookupTimeoutError,
    PostgresCohortMembershipRepository,
} from './postgres-cohort-membership-repository'

// Counter is a module-scoped global, so compare deltas rather than reset shared state between tests.
const outcomeCount = async (outcome: string): Promise<number> => {
    const metric = register.getSingleMetric('cdp_cohort_membership_lookups_total')
    if (!metric) {
        return 0
    }
    const data = await metric.get()
    return data.values.find((v) => (v.labels as Record<string, string>).outcome === outcome)?.value ?? 0
}

describe('PostgresCohortMembershipRepository', () => {
    let postgres: PostgresRouter
    let repository: PostgresCohortMembershipRepository

    beforeAll(async () => {
        postgres = new PostgresRouter(defaultConfig)
        await resetBehavioralCohortsDatabase(postgres)
    })

    afterAll(async () => {
        await postgres.end()
    })

    beforeEach(() => {
        repository = new PostgresCohortMembershipRepository(postgres)
    })

    it('returns the cohorts the person is currently in, scoped to the team', async () => {
        const teamId = 2
        const personUuid = new UUIDT().toString()
        await insertCohortMemberships(postgres, [
            { team_id: teamId, cohort_id: 101, person_id: personUuid, in_cohort: true },
            { team_id: teamId, cohort_id: 102, person_id: personUuid, in_cohort: false }, // person left
            { team_id: teamId + 1, cohort_id: 103, person_id: personUuid, in_cohort: true }, // another team, must not leak
            { team_id: teamId, cohort_id: 104, person_id: personUuid, in_cohort: true },
        ])

        const result = await repository.getMemberCohortIds(teamId, personUuid)

        expect(result.sort()).toEqual([101, 104])
    })

    it('returns an empty set for a person the pipeline never wrote a row for', async () => {
        const result = await repository.getMemberCohortIds(2, new UUIDT().toString())

        expect(result).toEqual([])
    })

    it('rejects with a retriable timeout error when the lookup hangs', async () => {
        jest.useFakeTimers()
        try {
            const hangingRouter = { query: () => new Promise(() => {}) } as unknown as PostgresRouter
            const hangingRepository = new PostgresCohortMembershipRepository(hangingRouter, 500)

            const lookup = hangingRepository.getMemberCohortIds(2, new UUIDT().toString())
            const assertion = expect(lookup).rejects.toThrow(CohortMembershipLookupTimeoutError)
            jest.advanceTimersByTime(500)
            await assertion
            await expect(lookup.catch((e) => e.isRetriable)).resolves.toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })

    it('records exactly one outcome when the query settles after timing out', async () => {
        jest.useFakeTimers()
        try {
            let resolveQuery!: (value: { rows: { cohort_id: string }[] }) => void
            const lateRouter = {
                query: () => new Promise((resolve) => (resolveQuery = resolve)),
            } as unknown as PostgresRouter
            const lateRepository = new PostgresCohortMembershipRepository(lateRouter, 500)

            const timeoutBefore = await outcomeCount('timeout')
            const successBefore = await outcomeCount('success')

            const lookup = lateRepository.getMemberCohortIds(2, new UUIDT().toString())
            jest.advanceTimersByTime(500)
            await expect(lookup).rejects.toThrow(CohortMembershipLookupTimeoutError)

            // The underlying query settles a moment later; its handler must not record a second outcome
            resolveQuery({ rows: [{ cohort_id: '101' }] })
            await Promise.resolve()
            await Promise.resolve()

            expect(await outcomeCount('timeout')).toBe(timeoutBefore + 1)
            expect(await outcomeCount('success')).toBe(successBefore)
        } finally {
            jest.useRealTimers()
        }
    })
})
