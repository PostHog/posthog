import { Team } from '../../../../types'
import { TeamId } from '../../../../types'
import { BackgroundRefresher } from '../../../../utils/background-refresher'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { logger as logger } from '../../../../utils/logger'
import { MessageWithTeam } from '../teams/types'
import { RetentionPeriod } from '../types'
import { MessageWithRetention } from './types'

export class RetentionService {
    private readonly retentionRefresher: BackgroundRefresher<Record<TeamId, RetentionPeriod>>

    constructor(private postgres: PostgresRouter) {
        this.retentionRefresher = new BackgroundRefresher(
            () => this.fetchTeamRetentionPeriods(),
            5 * 60 * 1000, // 5 minutes
            (e) => {
                // We ignore the error and wait for postgres to recover
                logger.error('Error refreshing team retention periods', e)
            }
        )
    }

    private async fetchTeamRetentionPeriods(): Promise<Record<TeamId, RetentionPeriod>> {
        return fetchTeamRetentionPeriods(this.postgres)
    }

    private async getRetentionByTeamId(teamId: TeamId): Promise<RetentionPeriod | null> {
        const retentionPeriods = await this.retentionRefresher.get()
        return retentionPeriods[teamId]
    }

    private async addRetentionToMessage(message: MessageWithTeam): Promise<MessageWithRetention> {
        const retentionPeriod = await this.getRetentionByTeamId(message.team.teamId)

        if (!retentionPeriod) {
            throw new Error(`Error during retention period lookup: Unknown team id ${message.team.teamId}`)
        }

        return {
            retentionPeriod: retentionPeriod,
            team: message.team,
            data: message.data,
        }
    }

    public async processBatch(messages: MessageWithTeam[]): Promise<MessageWithRetention[]> {
        // TODO: Look up session ID in Redis and add it to the messages
        // ....if not present, look it up in the backgroundrefresher and add it to Redis with 24h TTL
        return await Promise.all(messages.map((message) => this.addRetentionToMessage(message)))
    }
}

export async function fetchTeamRetentionPeriods(client: PostgresRouter): Promise<Record<TeamId, RetentionPeriod>> {
    const selectResult = await client.query<{ session_recording_retention_period: RetentionPeriod } & Pick<Team, 'id'>>(
        PostgresUse.COMMON_READ,
        `
            SELECT id, session_recording_retention_period
            FROM posthog_team
            WHERE session_recording_opt_in = true
        `,
        [],
        'fetchTeamTokensWithRecordings'
    )

    return selectResult.rows.reduce(
        (acc, row) => {
            acc[row.id] = row.session_recording_retention_period
            return acc
        },
        {} as Record<TeamId, RetentionPeriod>
    )
}
