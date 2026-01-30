import { Team, TeamId } from '../../types'
import { BackgroundRefresher } from '../../utils/background-refresher'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { logger } from '../../utils/logger'
import { RetentionPeriod } from '../types'
import { TeamServiceMetrics } from './metrics'
import { TeamForReplay } from './types'

export class TeamService {
    private readonly teamRefresher: BackgroundRefresher<
        [Record<string, TeamForReplay>, Record<TeamId, RetentionPeriod>, Record<TeamId, boolean>]
    >

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
        const tokenMap = (await this.teamRefresher.get())[0]
        const teamConfig = tokenMap[token]

        if (!teamConfig?.teamId) {
            return null
        }

        return teamConfig
    }

    public async getRetentionPeriodByTeamId(teamId: TeamId): Promise<RetentionPeriod | null> {
        const retentionMap = (await this.teamRefresher.get())[1]
        const retentionPeriod = retentionMap[teamId]

        if (retentionPeriod === undefined) {
            return null
        }

        return retentionPeriod
    }

    public async getEncryptionEnabledByTeamId(teamId: TeamId): Promise<boolean> {
        const encryptionMap = (await this.teamRefresher.get())[2]
        return encryptionMap[teamId] ?? false
    }

    private async fetchTeamTokensWithRecordings(): Promise<
        [Record<string, TeamForReplay>, Record<TeamId, RetentionPeriod>, Record<TeamId, boolean>]
    > {
        return fetchTeamTokensWithRecordings(this.postgres)
    }
}

export async function fetchTeamTokensWithRecordings(
    client: PostgresRouter
): Promise<[Record<string, TeamForReplay>, Record<TeamId, RetentionPeriod>, Record<TeamId, boolean>]> {
    const selectResult = await client.query<
        {
            capture_console_log_opt_in: boolean
            session_recording_retention_period: RetentionPeriod
            session_recording_encryption: boolean | null
        } & Pick<Team, 'id' | 'api_token'>
    >(
        PostgresUse.COMMON_READ,
        `
            SELECT id, api_token, capture_console_log_opt_in, session_recording_retention_period, session_recording_encryption
            FROM posthog_team
            WHERE session_recording_opt_in = true
        `,
        [],
        'fetchTeamTokensWithRecordings'
    )

    const tokenMap = selectResult.rows.reduce(
        (acc, row) => {
            acc[row.api_token] = {
                teamId: row.id,
                consoleLogIngestionEnabled: row.capture_console_log_opt_in,
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

    const encryptionMap = selectResult.rows.reduce(
        (acc, row) => {
            acc[row.id] = row.session_recording_encryption ?? false
            return acc
        },
        {} as Record<TeamId, boolean>
    )

    TeamServiceMetrics.incrementRefreshCount()

    return [tokenMap, retentionMap, encryptionMap]
}
