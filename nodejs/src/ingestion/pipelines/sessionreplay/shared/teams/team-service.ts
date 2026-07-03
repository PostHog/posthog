import { BackgroundRefresher } from '~/common/utils/background-refresher'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { Team, TeamId } from '~/types'

import { TeamServiceMetrics } from './metrics'
import { TeamForReplay } from './types'

interface TeamServiceData {
    tokenMap: Record<string, TeamForReplay>
    retentionMap: Record<TeamId, RetentionPeriod>
}

export class TeamService {
    private readonly teamRefresher: BackgroundRefresher<TeamServiceData>

    constructor(private postgres: PostgresRouter) {
        this.teamRefresher = new BackgroundRefresher(
            () => this.fetchTeamTokensWithRecordings(),
            5 * 60 * 1000, // 5 minutes
            (e) => {
                // We ignore the error and wait for postgres to recover
                logger.error('Error refreshing team tokens', e)
                TeamServiceMetrics.incrementRefreshErrors()
            }
        )
    }

    public async getTeamByToken(token: string): Promise<TeamForReplay | null> {
        const { tokenMap } = await this.teamRefresher.get()
        const teamConfig = tokenMap[token]

        if (!teamConfig?.teamId) {
            return null
        }

        return teamConfig
    }

    public async getRetentionPeriodByTeamId(teamId: TeamId): Promise<RetentionPeriod | null> {
        const { retentionMap } = await this.teamRefresher.get()
        const retentionPeriod = retentionMap[teamId]

        if (retentionPeriod === undefined) {
            return null
        }

        return retentionPeriod
    }

    private async fetchTeamTokensWithRecordings(): Promise<TeamServiceData> {
        return fetchTeamTokensWithRecordings(this.postgres)
    }
}

export async function fetchTeamTokensWithRecordings(client: PostgresRouter): Promise<TeamServiceData> {
    const selectResult = await client.query<
        {
            capture_console_log_opt_in: boolean
            session_recording_retention_period: RetentionPeriod
            is_ai_training_opted_in: boolean
        } & Pick<Team, 'id' | 'api_token'>
    >(
        PostgresUse.COMMON_READ,
        `
            SELECT
                t.id,
                t.api_token,
                t.capture_console_log_opt_in,
                t.session_recording_retention_period,
                COALESCE(o.is_ai_training_opted_in, false) AS is_ai_training_opted_in
            FROM posthog_team t
            LEFT JOIN posthog_organization o ON o.id = t.organization_id
            WHERE t.session_recording_opt_in = true
        `,
        [],
        'fetchTeamTokensWithRecordings'
    )

    const tokenMap = selectResult.rows.reduce(
        (acc, row) => {
            acc[row.api_token] = {
                teamId: row.id,
                consoleLogIngestionEnabled: row.capture_console_log_opt_in,
                aiTrainingOptedIn: row.is_ai_training_opted_in,
            }
            return acc
        },
        {} as Record<string, TeamForReplay>
    )

    const retentionMap = selectResult.rows.reduce(
        (acc, row) => {
            acc[row.id] = row.session_recording_retention_period
            return acc
        },
        {} as Record<TeamId, RetentionPeriod>
    )

    TeamServiceMetrics.incrementRefreshCount()

    return { tokenMap, retentionMap }
}
