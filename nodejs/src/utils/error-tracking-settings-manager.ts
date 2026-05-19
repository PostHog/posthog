import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

export interface ErrorTrackingSettings {
    projectRateLimitValue: number | null
    projectRateLimitBucketSizeMinutes: number | null
}

interface RawSettingsRow {
    team_id: number
    project_rate_limit_value: number | null
    project_rate_limit_bucket_size_minutes: number | null
}

export class ErrorTrackingSettingsManager {
    private lazyLoader: LazyLoader<ErrorTrackingSettings>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'ErrorTrackingSettingsManager',
            refreshAgeMs: 2 * 60 * 1000,
            refreshJitterMs: 30 * 1000,
            loader: async (teamIds: string[]) => {
                return await this.fetchSettings(teamIds)
            },
        })
    }

    public async getSettings(teamId: number): Promise<ErrorTrackingSettings | null> {
        return await this.lazyLoader.get(String(teamId))
    }

    private async fetchSettings(teamIds: string[]): Promise<Record<string, ErrorTrackingSettings | null>> {
        const numericTeamIds = teamIds.map(Number).filter((id) => !isNaN(id) && id > 0)

        const result: Record<string, ErrorTrackingSettings | null> = {}
        for (const id of teamIds) {
            result[id] = null
        }

        if (numericTeamIds.length === 0) {
            return result
        }

        const queryResult = await this.postgres.query<RawSettingsRow>(
            PostgresUse.COMMON_READ,
            `SELECT
                team_id,
                project_rate_limit_value,
                project_rate_limit_bucket_size_minutes
            FROM posthog_errortrackingsettings
            WHERE team_id = ANY($1)`,
            [numericTeamIds],
            'fetch-error-tracking-settings'
        )

        for (const row of queryResult.rows) {
            result[String(row.team_id)] = {
                projectRateLimitValue: row.project_rate_limit_value,
                projectRateLimitBucketSizeMinutes: row.project_rate_limit_bucket_size_minutes,
            }
        }

        return result
    }
}
