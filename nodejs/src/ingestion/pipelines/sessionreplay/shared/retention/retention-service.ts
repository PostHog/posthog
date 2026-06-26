import { SessionBatchMetrics } from '~/ingestion/pipelines/sessionreplay/sessions/metrics'
import {
    RetentionPeriod,
    RetentionPeriodToDaysMap,
    ValidRetentionPeriods,
} from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { RedisPool, TeamId } from '~/types'
import { logger } from '~/utils/logger'

import { RetentionServiceMetrics } from './metrics'

function isValidRetentionPeriod(retentionPeriod: string): retentionPeriod is RetentionPeriod {
    return ValidRetentionPeriods.includes(retentionPeriod as RetentionPeriod)
}

export class RetentionService {
    constructor(
        private redisPool: RedisPool,
        private teamService: TeamService,
        private keyPrefix = '@posthog/replay/',
        private redisTimeoutMs = 200
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

        if (!isValidRetentionPeriod(retentionPeriod)) {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new Error(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
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

        if (retentionPeriod === null) {
            retentionPeriod = await this.getRetentionByTeamId(teamId)

            this.setSessionRetentionInRedis(sessionId, retentionPeriod).catch((error) => {
                logger.warn('🔁', 'retention_service_redis_set_error', {
                    error: String(error),
                    sessionId,
                    teamId,
                })
            })
        }

        if (isValidRetentionPeriod(retentionPeriod)) {
            return retentionPeriod
        }

        RetentionServiceMetrics.incrementLookupErrors()
        throw new Error(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
    }

    public async getSessionRetentionDays(teamId: TeamId, sessionId: string): Promise<number> {
        const retentionPeriod = await this.getSessionRetention(teamId, sessionId)
        return RetentionPeriodToDaysMap[retentionPeriod]
    }

    private async getSessionRetentionFromRedis(sessionId: string): Promise<string | null> {
        const redisKey = this.generateRedisKey(sessionId)
        const client = await this.redisPool.acquire()

        try {
            return await Promise.race([
                client.get(redisKey),
                new Promise<never>((_, reject) =>
                    setTimeout(() => reject(new Error('Redis GET timed out')), this.redisTimeoutMs)
                ),
            ])
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async setSessionRetentionInRedis(sessionId: string, retentionPeriod: string): Promise<void> {
        const redisKey = this.generateRedisKey(sessionId)
        const client = await this.redisPool.acquire()

        try {
            await Promise.race([
                client.set(redisKey, retentionPeriod, 'EX', 24 * 60 * 60),
                new Promise<never>((_, reject) =>
                    setTimeout(() => reject(new Error('Redis SET timed out')), this.redisTimeoutMs)
                ),
            ])
        } finally {
            await this.redisPool.release(client)
        }
    }
}
