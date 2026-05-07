import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { ErrorTrackingSettingsManager } from './error-tracking-settings-manager'

describe('ErrorTrackingSettingsManager', () => {
    let hub: Hub
    let manager: ErrorTrackingSettingsManager
    let postgres: PostgresRouter
    let teamId: Team['id']
    let fetchSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        await resetTestDatabase()
        hub = await createHub()

        postgres = new PostgresRouter(defaultConfig)
        manager = new ErrorTrackingSettingsManager(postgres)
        const team = await getFirstTeam(hub.postgres)
        teamId = team.id
        fetchSpy = jest.spyOn(manager as any, 'fetchSettings')
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await postgres.end()
        await closeHub(hub)
    })

    const upsertSettings = async (
        targetTeamId: number,
        projectRateLimitValue: number | null,
        projectRateLimitBucketSizeMinutes: number | null
    ): Promise<void> => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_errortrackingsettings
                (team_id, project_rate_limit_value, project_rate_limit_bucket_size_minutes,
                 per_issue_rate_limit_value, per_issue_rate_limit_bucket_size_minutes)
             VALUES ($1, $2, $3, NULL, NULL)
             ON CONFLICT (team_id) DO UPDATE SET
                project_rate_limit_value = EXCLUDED.project_rate_limit_value,
                project_rate_limit_bucket_size_minutes = EXCLUDED.project_rate_limit_bucket_size_minutes`,
            [targetTeamId, projectRateLimitValue, projectRateLimitBucketSizeMinutes],
            'upsert-test-error-tracking-settings'
        )
    }

    it('returns null when the team has no row', async () => {
        const result = await manager.getSettings(teamId)
        expect(result).toBeNull()
    })

    it('returns settings when the team has a row', async () => {
        await upsertSettings(teamId, 100, 5)

        const result = await manager.getSettings(teamId)
        expect(result).toEqual({
            projectRateLimitValue: 100,
            projectRateLimitBucketSizeMinutes: 5,
        })
    })

    it('returns null fields when row exists but values are unset', async () => {
        await upsertSettings(teamId, null, null)

        const result = await manager.getSettings(teamId)
        expect(result).toEqual({
            projectRateLimitValue: null,
            projectRateLimitBucketSizeMinutes: null,
        })
    })

    it('caches results across calls within the refresh window', async () => {
        await upsertSettings(teamId, 50, 15)

        await manager.getSettings(teamId)
        await manager.getSettings(teamId)
        await manager.getSettings(teamId)

        expect(fetchSpy).toHaveBeenCalledTimes(1)
    })

    it('coalesces concurrent lookups into a single fetch', async () => {
        await upsertSettings(teamId, 100, 5)

        await Promise.all([manager.getSettings(teamId), manager.getSettings(teamId), manager.getSettings(teamId)])

        expect(fetchSpy).toHaveBeenCalledTimes(1)
    })
})
