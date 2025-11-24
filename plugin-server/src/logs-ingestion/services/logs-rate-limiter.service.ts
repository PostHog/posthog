import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { Hub } from '~/types'

import { LogsIngestionMessage } from '../types'

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/logs-rate-limiter' : '@posthog/logs-rate-limiter'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`

export type LogsRateLimit = {
    tokensBefore: number
    tokensAfter: number
    isRateLimited: boolean
}

export type FilteredMessages = {
    allowed: LogsIngestionMessage[]
    dropped: LogsIngestionMessage[]
}

/**
 * The LogsRateLimiterService is used to rate limit logs ingestion to ensure we aren't allowing too many logs to be ingested at once.
 * The key part is we specify the refill rate as our per second KB/s limit. and the bucket size as the amount we are allowed to burst to.
 * The burst shouldn't be too much higher.
 */
export class LogsRateLimiterService {
    constructor(
        private hub: Hub,
        private redis: RedisV2
    ) {}

    private rateLimitArgs(id: string, cost: number): [string, number, number, number, number, number] {
        const nowSeconds = Math.round(Date.now() / 1000)

        return [
            `${REDIS_KEY_TOKENS}/${id}`,
            nowSeconds,
            cost,
            this.hub.LOGS_LIMITER_BUCKET_SIZE_KB,
            this.hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND,
            this.hub.LOGS_LIMITER_TTL_SECONDS,
        ]
    }

    public async rateLimitMany(idCosts: [string, number][]): Promise<[string, LogsRateLimit][]> {
        const res = await this.redis.usePipeline({ name: 'logs-rate-limiter', failOpen: true }, (pipeline) => {
            idCosts.forEach(([id, cost]) => {
                pipeline.checkRateLimit(...this.rateLimitArgs(id, cost))
            })
        })

        if (!res) {
            throw new Error('Failed to rate limit')
        }

        return idCosts.map(([id], index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensBefore = Number(tokenRes[1]?.[0] ?? this.hub.LOGS_LIMITER_BUCKET_SIZE_KB)
            const tokensAfter = Number(tokenRes[1]?.[1] ?? this.hub.LOGS_LIMITER_BUCKET_SIZE_KB)
            return [
                id,
                {
                    tokensBefore,
                    tokensAfter,
                    isRateLimited: tokensAfter <= 0,
                },
            ]
        })
    }

    private isRateLimitingEnabledForTeam(teamId: number): boolean {
        const enabledTeams = this.hub.LOGS_LIMITER_ENABLED_TEAMS
        if (enabledTeams === '*') {
            return true
        }
        if (!enabledTeams) {
            return false
        }
        const teamIds = enabledTeams.split(',').map((id) => parseInt(id.trim(), 10))
        return teamIds.includes(teamId)
    }

    public async filterMessages(messages: LogsIngestionMessage[]): Promise<FilteredMessages> {
        // Group messages by team to calculate total cost per team (only for teams with rate limiting enabled)
        const teamCosts = new Map<number, number>()
        for (const message of messages) {
            if (!this.isRateLimitingEnabledForTeam(message.teamId)) {
                continue
            }
            const currentCost = teamCosts.get(message.teamId) ?? 0
            // Cost is in KB (uncompressed bytes / 1024)
            const costKb = Math.ceil(message.bytesUncompressed / 1024)
            teamCosts.set(message.teamId, currentCost + costKb)
        }

        // Check rate limits for all teams
        const rateLimitResults = await this.rateLimitMany(
            Array.from(teamCosts.entries()).map(([teamId, cost]) => [teamId.toString(), cost])
        )

        // Build a map of team rate limit results
        const teamLimits = new Map<number, { tokensBefore: number; tokensAfter: number; isRateLimited: boolean }>()
        for (const [teamIdStr, result] of rateLimitResults) {
            teamLimits.set(parseInt(teamIdStr, 10), result)
        }

        // Filter messages based on rate limits, allowing partial batches through
        const allowed: LogsIngestionMessage[] = []
        const dropped: LogsIngestionMessage[] = []
        const teamKbUsed = new Map<number, number>()

        for (const message of messages) {
            const limit = teamLimits.get(message.teamId)
            if (!limit) {
                // No rate limit for this team (either not enabled or not in the map)
                allowed.push(message)
                continue
            }

            const kbUsed = teamKbUsed.get(message.teamId) ?? 0
            const availableKb = limit.tokensBefore
            const messageKb = Math.ceil(message.bytesUncompressed / 1024)

            // Allow message if we haven't exceeded the available tokens
            if (kbUsed + messageKb <= availableKb) {
                allowed.push(message)
                teamKbUsed.set(message.teamId, kbUsed + messageKb)
            } else {
                dropped.push(message)
            }
        }

        return { allowed, dropped }
    }
}
