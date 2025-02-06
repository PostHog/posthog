import { TeamIDWithConfig } from '~/src/types'

import { fetchTeamTokensWithRecordings } from '../../../services/team-manager'
import { BackgroundRefresher } from '../../../utils/background-refresher'
import { PostgresRouter } from '../../../utils/db/postgres'
import { status as logger } from '../../../utils/status'
import { Team } from './types'

export class TeamService {
    private readonly teamRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>

    constructor(postgres: PostgresRouter) {
        this.teamRefresher = new BackgroundRefresher(
            () => fetchTeamTokensWithRecordings(postgres),
            5 * 60 * 1000, // 5 minutes
            (e) => {
                // We ignore the error and wait for postgres to recover
                logger.error('Error refreshing team tokens', e)
            }
        )
    }

    public async getTeamByToken(token: string): Promise<Team | null> {
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
}
