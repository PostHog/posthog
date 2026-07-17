import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { ValidRetentionPeriods } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { TeamService } from './team-service'

describe('TeamService (integration)', () => {
    let postgres: PostgresRouter
    let teamId: number
    let apiToken: string

    beforeEach(async () => {
        await resetTestDatabase()
        postgres = new PostgresRouter(defaultConfig)
        const team = await getFirstTeam(postgres)
        teamId = team.id
        apiToken = team.api_token
    })

    afterEach(async () => {
        await postgres.end()
    })

    // Driven off the authoritative allowed set: every period Postgres is allowed to hold must store
    // and deserialize, and a newly added period is covered here automatically.
    it.each([...ValidRetentionPeriods])(
        'stores and deserializes retention period %s from a real Postgres row',
        async (period) => {
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET session_recording_retention_period = $1 WHERE id = $2`,
                [period, teamId],
                'test-set-retention'
            )
            const teamService = new TeamService(postgres)

            expect(await teamService.getRetentionPeriodByTeamId(teamId)).toBe(period)
        }
    )

    it('deserializes the team token', async () => {
        const teamService = new TeamService(postgres)
        expect(await teamService.getTeamByToken(apiToken)).toMatchObject({ teamId })
    })
})
