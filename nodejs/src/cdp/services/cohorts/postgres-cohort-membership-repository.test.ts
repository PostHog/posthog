import { defaultConfig } from '~/common/config/config'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { resetBehavioralCohortsDatabase } from '~/tests/helpers/sql'

import { insertCohortMemberships } from '../../_tests/fixtures'
import {
    CohortMembershipLookupTimeoutError,
    PostgresCohortMembershipRepository,
} from './postgres-cohort-membership-repository'

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
})
