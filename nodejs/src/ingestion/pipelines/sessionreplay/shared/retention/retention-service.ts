import { SessionBatchMetrics } from '~/ingestion/pipelines/sessionreplay/sessions/metrics'
import {
    RetentionPeriod,
    RetentionPeriodToDaysMap,
    ValidRetentionPeriods,
} from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { RedisPool, TeamId } from '~/types'

import { RetentionServiceMetrics } from './metrics'

function isValidRetentionPeriod(retentionPeriod: string): retentionPeriod is RetentionPeriod {
    return ValidRetentionPeriods.includes(retentionPeriod as RetentionPeriod)
}

export class RetentionService {
    constructor(
        private redisPool: RedisPool,
        private teamService: TeamService,
        private keyPrefix = '@posthog/replay/'
    ) {}

    private generateRedisKey(sessionId: string): string {
        return `${this.keyPrefix}session-retention-${sessionId}`
    }

    public async getRetentionByTeamId(teamId: TeamId): Promise<RetentionPeriod> {
        const retentionPeriod = await this.teamService.getRetentionPeriodByTeamId(teamId)

        if (retentionPeriod === null) {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new Error(`Error during retention period lookup: Unknown team id ${teamId}`)
        }

        return retentionPeriod
    }

    public async getSessionRetention(teamId: TeamId, sessionId: string): Promise<RetentionPeriod> {
        let retentionPeriod: string | null = null

        const startTime = performance.now()
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
            SessionBatchMetrics.observeRetentionRedisLatency((performance.now() - startTime) / 1000)
        }

        if (retentionPeriod !== null && isValidRetentionPeriod(retentionPeriod)) {
            return retentionPeriod
        } else {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new Error(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
        }
    }

    public async getSessionRetentionDays(teamId: TeamId, sessionId: string): Promise<number> {
        const retentionPeriod = await this.getSessionRetention(teamId, sessionId)
        const retentionPeriodDays = RetentionPeriodToDaysMap[retentionPeriod]

        if (retentionPeriodDays !== null) {
            return retentionPeriodDays
        } else {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new Error(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
        }
    }
}
