import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'

import { resetBehavioralCohortsDatabase } from '../../../../tests/helpers/sql'
import { RealtimeCohortAudienceService } from './realtime-cohort-audience.service'

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
})
