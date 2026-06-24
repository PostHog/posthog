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

const DEFAULT_REDIS_TIMEOUT_MS = 5000

export class RetentionService {
    constructor(
        private redisPool: RedisPool,
        private teamService: TeamService,
        private keyPrefix = '@posthog/replay/',
        private redisTimeoutMs = DEFAULT_REDIS_TIMEOUT_MS
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
        let client
        const redisKey = this.generateRedisKey(sessionId)

        try {
            const redisOp = async () => {
                client = await this.redisPool.acquire()

                const cached = await client.get(redisKey)
                if (cached !== null) {
                    return cached
                }

                const fromDb = await this.getRetentionByTeamId(teamId)
                await client.set(redisKey, fromDb, 'EX', 24 * 60 * 60)
                return fromDb
            }
            const timeout = new Promise<never>((_, reject) =>
                setTimeout(() => reject(new Error(`Redis timeout after ${this.redisTimeoutMs}ms`)), this.redisTimeoutMs)
            )

            retentionPeriod = await Promise.race([redisOp(), timeout])
        } finally {
            if (client) {
                await this.redisPool.release(client)
            }
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
