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

    it('resolves membership from cohort_membership rows, scoped to the team', async () => {
        const teamId = 2
        const personUuid = new UUIDT().toString()
        await insertCohortMemberships(postgres, [
            { team_id: teamId, cohort_id: 101, person_id: personUuid, in_cohort: true },
            { team_id: teamId, cohort_id: 102, person_id: personUuid, in_cohort: false },
            { team_id: teamId + 1, cohort_id: 103, person_id: personUuid, in_cohort: true },
        ])

        const result = await repository.getMemberships(teamId, personUuid, [101, 102, 103, 104])

        expect(result).toEqual(
            new Map([
                [101, true], // in_cohort=true row
                [102, false], // in_cohort=false row (person left)
                [103, false], // row belongs to another team — must not leak
                [104, false], // no row at all
            ])
        )
    })

    it('short-circuits on an empty cohort id list without querying', async () => {
        const querySpy = jest.spyOn(postgres, 'query')

        const result = await repository.getMemberships(2, new UUIDT().toString(), [])

        expect(result).toEqual(new Map())
        expect(querySpy).not.toHaveBeenCalled()
        querySpy.mockRestore()
    })

    it('rejects with a retriable timeout error when the lookup hangs', async () => {
        jest.useFakeTimers()
        try {
            const hangingRouter = { query: () => new Promise(() => {}) } as unknown as PostgresRouter
            const hangingRepository = new PostgresCohortMembershipRepository(hangingRouter, 500)

            const lookup = hangingRepository.getMemberships(2, new UUIDT().toString(), [1])
            const assertion = expect(lookup).rejects.toThrow(CohortMembershipLookupTimeoutError)
            jest.advanceTimersByTime(500)
            await assertion
            await expect(lookup.catch((e) => e.isRetriable)).resolves.toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })
})
