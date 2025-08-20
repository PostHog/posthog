import { RedisPool, Team } from '../../../../types'
import { TeamId } from '../../../../types'
import { BackgroundRefresher } from '../../../../utils/background-refresher'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { logger } from '../../../../utils/logger'
import { ValidRetentionPeriods } from '../constants'
import { RetentionPeriod } from '../types'
import { RetentionServiceMetrics } from './metrics'

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

    public async getSessionRetention(teamId: TeamId, sessionId: string): Promise<RetentionPeriod> {
        let retentionPeriod: string | null = null

        const client = await this.redisPool.acquire()
        const redisKey = this.generateRedisKey(sessionId)

        try {
            // Attempt to look up the retention period for the session in Redis
            retentionPeriod = await client.get(redisKey)

            // ...if no retention period exists for the session
            if (retentionPeriod === null) {
                // ...get the value from Postgres
                retentionPeriod = await this.getRetentionByTeamId(teamId)

                // ...and then set it in Redis for future batches, with a TTL of 24 hours
                await client.set(redisKey, retentionPeriod, 'EX', 24 * 60 * 60)
            }
        } finally {
            await this.redisPool.release(client)
        }

        if (retentionPeriod !== null && isValidRetentionPeriod(retentionPeriod)) {
            return retentionPeriod
        } else {
            throw new Error(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
        }
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
