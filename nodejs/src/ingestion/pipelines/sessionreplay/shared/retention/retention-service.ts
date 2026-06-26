import { logger } from '~/common/utils/logger'
import { SessionBatchMetrics } from '~/ingestion/pipelines/sessionreplay/sessions/metrics'
import {
    RetentionPeriod,
    RetentionPeriodToDaysMap,
    ValidRetentionPeriods,
} from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { RedisPool, TeamId } from '~/types'

import { RetentionServiceMetrics } from './metrics'

export class RetentionLookupError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'RetentionLookupError'
    }
}

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
            throw new RetentionLookupError(`Error during retention period lookup: Unknown team id ${teamId}`)
        }

        if (!isValidRetentionPeriod(retentionPeriod)) {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new RetentionLookupError(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
        }

        return retentionPeriod
    }

    public async getSessionRetention(teamId: TeamId, sessionId: string): Promise<RetentionPeriod> {
        const startTime = performance.now()
        let retentionPeriod: string | null = null

        try {
            retentionPeriod = await this.getSessionRetentionFromRedis(sessionId)
        } catch (error) {
            SessionBatchMetrics.incrementRetentionRedisFallbacks()
            logger.warn('🔁', 'retention_service_redis_fallback', {
                error: String(error),
                sessionId,
                teamId,
            })
        } finally {
            SessionBatchMetrics.observeRetentionRedisLatency((performance.now() - startTime) / 1000)
        }

        if (retentionPeriod !== null && isValidRetentionPeriod(retentionPeriod)) {
            return retentionPeriod
        }

        if (retentionPeriod !== null) {
            SessionBatchMetrics.incrementRetentionRedisFallbacks()
            logger.warn('🔁', 'retention_service_redis_invalid_value', {
                value: retentionPeriod,
                sessionId,
                teamId,
            })
        }

        const resolved = await this.getRetentionByTeamId(teamId)

        this.setSessionRetentionInRedis(sessionId, resolved).catch((error) => {
            logger.warn('🔁', 'retention_service_redis_set_error', {
                error: String(error),
                sessionId,
                teamId,
            })
        })

        return resolved
    }

    public async getSessionRetentionDays(teamId: TeamId, sessionId: string): Promise<number> {
        const retentionPeriod = await this.getSessionRetention(teamId, sessionId)
        return RetentionPeriodToDaysMap[retentionPeriod]
    }

    private async getSessionRetentionFromRedis(sessionId: string): Promise<string | null> {
        const redisKey = this.generateRedisKey(sessionId)
        const client = await this.redisPool.acquire()

        try {
            return await client.get(redisKey)
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async setSessionRetentionInRedis(sessionId: string, retentionPeriod: string): Promise<void> {
        const redisKey = this.generateRedisKey(sessionId)
        const client = await this.redisPool.acquire()

        try {
            await client.set(redisKey, retentionPeriod, 'EX', 24 * 60 * 60)
        } finally {
            await this.redisPool.release(client)
        }
    }
}
