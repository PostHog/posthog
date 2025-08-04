import { TeamIDWithConfig } from '../../../../cdp/consumers/cdp-base.consumer'
import { Team } from '../../../../types'
import { BackgroundRefresher } from '../../../../utils/background-refresher'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { logger as logger } from '../../../../utils/logger'
import { TeamForReplay } from './types'

export class TeamService {
    private readonly teamRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>

    constructor(private postgres: PostgresRouter) {
        this.teamRefresher = new BackgroundRefresher(
            () => this.fetchTeamTokensWithRecordings(),
            5 * 60 * 1000, // 5 minutes
            (e) => {
                // We ignore the error and wait for postgres to recover
                logger.error('Error refreshing team tokens', e)
            }
        )
    }

    public async getTeamByToken(token: string): Promise<TeamForReplay | null> {
        const teams = await this.teamRefresher.get()
        const teamConfig = teams[token]

        if (!teamConfig?.teamId) {
            return null
        }

        return {
            teamId: teamConfig.teamId,
            consoleLogIngestionEnabled: teamConfig.consoleLogIngestionEnabled,
        }
    }

    private async fetchTeamTokensWithRecordings(): Promise<Record<string, TeamIDWithConfig>> {
        return fetchTeamTokensWithRecordings(this.postgres)
    }
}

export async function fetchTeamTokensWithRecordings(client: PostgresRouter): Promise<Record<string, TeamIDWithConfig>> {
    const selectResult = await client.query<{ capture_console_log_opt_in: boolean } & Pick<Team, 'id' | 'api_token'>>(
        PostgresUse.COMMON_READ,
        `
            SELECT id, api_token, capture_console_log_opt_in
            FROM posthog_team
            WHERE session_recording_opt_in = true
        `,
        [],
        'fetchTeamTokensWithRecordings'
    )

    return selectResult.rows.reduce(
        (acc, row) => {
            acc[row.api_token] = { teamId: row.id, consoleLogIngestionEnabled: row.capture_console_log_opt_in }
            return acc
        },
        {} as Record<string, TeamIDWithConfig>
    )
}
