import { RedisPool, Team } from '../../../../types'
import { TeamId } from '../../../../types'
import { BackgroundRefresher } from '../../../../utils/background-refresher'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { logger } from '../../../../utils/logger'
import { ValidRetentionPeriods } from '../constants'
import { MessageWithTeam } from '../teams/types'
import { RetentionPeriod } from '../types'
import { RetentionServiceMetrics } from './metrics'
import { MessageWithRetention } from './types'

function isValidRetentionPeriod(retentionPeriod: string): retentionPeriod is RetentionPeriod {
    return ValidRetentionPeriods.includes(retentionPeriod as RetentionPeriod)
}

export class RetentionService {
    private readonly retentionRefresher: BackgroundRefresher<Record<TeamId, RetentionPeriod>>

    constructor(
        private postgres: PostgresRouter,
        private redisPool: RedisPool,
        private keyPrefix = '@posthog/replay/'
    ) {
        this.retentionRefresher = new BackgroundRefresher(
            () => this.fetchTeamRetentionPeriods(),
            5 * 60 * 1000, // 5 minutes
            (e) => {
                // We log and count the error and wait for postgres to recover
                logger.error('Error refreshing team retention periods', e)
                RetentionServiceMetrics.incrementRefreshErrors()
            }
        )
    }

    private async fetchTeamRetentionPeriods(): Promise<Record<TeamId, RetentionPeriod>> {
        return fetchTeamRetentionPeriods(this.postgres)
    }

    private generateRedisKey(sessionId: string): string {
        return `${this.keyPrefix}session-retention-${sessionId}`
    }

    public async getRetentionByTeamId(teamId: TeamId): Promise<RetentionPeriod> {
        const retentionPeriods = await this.retentionRefresher.get()

        if (!(teamId in retentionPeriods)) {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new Error(`Error during retention period lookup: Unknown team id ${teamId}`)
        }

        return retentionPeriods[teamId]
    }

    public async addRetentionToMessage(message: MessageWithTeam): Promise<MessageWithRetention> {
        let retentionPeriod: string | null = null

        const client = await this.redisPool.acquire()
        const redisKey = this.generateRedisKey(message.data.session_id)

        try {
            // Check if the session already had a retention period set in Redis
            if ((await client.exists(redisKey)) === 1) {
                // ...if so, fetch it
                retentionPeriod = await client.get(redisKey)
            } else {
                // ...otherwise, get the value from Postgres
                retentionPeriod = await this.getRetentionByTeamId(message.team.teamId)

                // ...and then set it in Redis for future batches
                await client.set(redisKey, retentionPeriod)

                // ...and set TTL to 24 hours
                await client.expire(redisKey, 24 * 60 * 60)
            }
        } finally {
            await this.redisPool.release(client)
        }

        if (retentionPeriod !== null && isValidRetentionPeriod(retentionPeriod)) {
            return {
                retentionPeriod: retentionPeriod,
                team: message.team,
                data: message.data,
            }
        } else {
            throw new Error(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
        }
    }

    public async processBatch(messages: MessageWithTeam[]): Promise<MessageWithRetention[]> {
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
        'fetchTeamRetentionPeriods'
    )

    const rows = selectResult.rows.reduce(
        (acc, row) => {
            acc[row.id] = row.session_recording_retention_period
            return acc
        },
        {} as Record<TeamId, RetentionPeriod>
    )

    RetentionServiceMetrics.incrementRefreshCount()

    return rows
}
