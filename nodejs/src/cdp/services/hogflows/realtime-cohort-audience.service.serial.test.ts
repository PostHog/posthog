import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'

import { resetBehavioralCohortsDatabase } from '../../../../tests/helpers/sql'
import { MEMBER_PAGE_DEADLINE_MS, RealtimeCohortAudienceService } from './realtime-cohort-audience.service'

describe('RealtimeCohortAudienceService', () => {
    const TEAM_ID = 4242
    const COHORT_ID = 91204

    let postgres: PostgresRouter
    let service: RealtimeCohortAudienceService

    beforeEach(async () => {
        postgres = new PostgresRouter(defaultConfig)
        await resetBehavioralCohortsDatabase(postgres)
        service = new RealtimeCohortAudienceService(postgres)
    })

    afterEach(async () => {
        await postgres.end()
    })

    const insertMembership = async (teamId: number, cohortId: number, inCohort: boolean): Promise<string> => {
        const personId = new UUIDT().toString()
        await postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort) VALUES ($1, $2, $3, $4)`,
            [teamId, cohortId, personId, inCohort],
            'test'
        )
        return personId
    }

    it('pages every current member of the cohort exactly once, and nobody else', async () => {
        const members = await Promise.all([1, 2, 3].map(() => insertMembership(TEAM_ID, COHORT_ID, true)))
        await insertMembership(TEAM_ID, COHORT_ID, false)
        await insertMembership(TEAM_ID, COHORT_ID + 1, true)
        // The same cohort id under another team must never reach this audience.
        await insertMembership(TEAM_ID + 1, COHORT_ID, true)

        const collected: string[] = []
        let cursor: string | null = null
        for (let pages = 0; pages < 10; pages++) {
            const page = await service.getMemberPage(TEAM_ID, COHORT_ID, cursor, 2)
            collected.push(...page.ids)
            cursor = page.cursor
            if (!page.has_more) {
                break
            }
        }

        expect(collected).toEqual([...members].sort())
    })

    it.each([
        ['the connection checkout', () => new Promise(() => {}), undefined],
        ['a query', undefined, () => new Promise(() => {})],
    ])('rejects at the deadline and ends the connection when %s stalls', async (_stage, connect, query) => {
        jest.useFakeTimers()
        try {
            const client = { on: jest.fn(), removeListener: jest.fn(), release: jest.fn(), query }
            const stalledRouter = {
                connect: connect ?? (() => Promise.resolve(client)),
            } as unknown as PostgresRouter
            const page = new RealtimeCohortAudienceService(stalledRouter).getMemberPage(TEAM_ID, COHORT_ID, null)
            const outcome = expect(page).rejects.toThrow('took longer than')
            await jest.advanceTimersByTimeAsync(MEMBER_PAGE_DEADLINE_MS)
            await outcome
            if (query) {
                // Releasing with an error makes the pool end the connection instead of reusing it.
                expect(client.release).toHaveBeenCalledWith(expect.any(Error))
            }
        } finally {
            jest.useRealTimers()
        }
    })
})
