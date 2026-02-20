import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { Hub } from '~/types'

import { LogsIngestionMessage } from '../types'

/** Convert milliseconds to seconds */
const msToSeconds = (ms: number): number => Math.round(ms / 1000)

/** Convert bytes to kilobytes (rounded up) */
const bytesToKb = (bytes: number): number => Math.ceil(bytes / 1000)

/** Narrowed Hub type for LogsRateLimiterService */
export type LogsRateLimiterServiceHub = Pick<
    Hub,
    | 'LOGS_LIMITER_TEAM_BUCKET_SIZE_KB'
    | 'LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND'
    | 'LOGS_LIMITER_DISABLED_FOR_TEAMS'
    | 'LOGS_LIMITER_ENABLED_TEAMS'
    | 'LOGS_LIMITER_BUCKET_SIZE_KB'
    | 'LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND'
    | 'LOGS_LIMITER_TTL_SECONDS'
>

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
    private teamBucketSizes: Map<number, number>
    private teamRefillRates: Map<number, number>
    private disabledTeamIds: Set<number> | '*' | null
    private enabledTeamIds: Set<number> | '*' | null

    constructor(
        private hub: LogsRateLimiterServiceHub,
        private redis: RedisV2
    ) {
        this.teamBucketSizes = this.parseTeamConfig(hub.LOGS_LIMITER_TEAM_BUCKET_SIZE_KB)
        this.teamRefillRates = this.parseTeamConfig(hub.LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND)
        this.disabledTeamIds = this.parseTeamIdList(hub.LOGS_LIMITER_DISABLED_FOR_TEAMS)
        this.enabledTeamIds = this.parseTeamIdList(hub.LOGS_LIMITER_ENABLED_TEAMS)
    }

    private parseTeamIdList(config: string): Set<number> | '*' | null {
        if (config === '*') {
            return '*'
        }
        if (!config) {
            return null
        }
        const ids = new Set<number>()
        for (const id of config.split(',')) {
            const parsed = parseInt(id.trim(), 10)
            if (!isNaN(parsed)) {
                ids.add(parsed)
            }
        }
        return ids
    }

    private parseTeamConfig(config: string): Map<number, number> {
        const result = new Map<number, number>()
        if (!config) {
            return result
        }
        for (const entry of config.split(',')) {
            const [teamId, value] = entry.split(':').map((s) => parseInt(s.trim(), 10))
            if (!isNaN(teamId) && !isNaN(value)) {
                result.set(teamId, value)
            }
        }
        return result
    }

    private rateLimitArgs(
        id: string,
        cost: number,
        nowSeconds: number
    ): [string, number, number, number, number, number] {
        const teamId = parseInt(id, 10)

        return [
            `${REDIS_KEY_TOKENS}/${id}`,
            nowSeconds,
            cost,
            this.teamBucketSizes.get(teamId) ?? this.hub.LOGS_LIMITER_BUCKET_SIZE_KB,
            this.teamRefillRates.get(teamId) ?? this.hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND,
            this.hub.LOGS_LIMITER_TTL_SECONDS,
        ]
    }

    private getHeaderValue(headers: any[] | undefined, key: string): string | undefined {
        if (!headers || !Array.isArray(headers)) {
            return undefined
        }

        for (const header of headers) {
            if (header[key]) {
                // Convert Buffer to string
                return Buffer.from(header[key]).toString('utf8')
            }
        }
        return undefined
    }

    private getTimestampFromMessage(message: LogsIngestionMessage): number {
        const createdAtHeader = this.getHeaderValue(message.message.headers, 'created_at')
        if (createdAtHeader) {
            const timestamp = Date.parse(createdAtHeader) // Parse RFC3339/ISO8601 string
            if (!isNaN(timestamp)) {
                return msToSeconds(timestamp)
            }
        }
        // Fallback to current time
        return msToSeconds(Date.now())
    }

    public async rateLimitMany(idCosts: [string, number, number][]): Promise<[string, LogsRateLimit][]> {
        const res = await this.redis.usePipeline({ name: 'logs-rate-limiter', failOpen: true }, (pipeline) => {
            idCosts.forEach(([id, cost, nowSeconds]) => {
                pipeline.checkRateLimitV2(...this.rateLimitArgs(id, cost, nowSeconds))
            })
        })

        if (!res) {
            throw new Error('Failed to rate limit')
        }

        return idCosts.map(([id, ,], index) => {
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
        if (this.disabledTeamIds === '*') {
            return false
        }

        if (this.disabledTeamIds?.has(teamId)) {
            return false
        }

        if (this.enabledTeamIds === '*') {
            return true
        }

        if (!this.enabledTeamIds) {
            return false
        }

        return this.enabledTeamIds.has(teamId)
    }

    public async filterMessages(messages: LogsIngestionMessage[]): Promise<FilteredMessages> {
        // Group messages by team to calculate total cost per team (only for teams with rate limiting enabled)
        const teamCosts = new Map<number, number>()
        const teamTimestamps = new Map<number, number>()

        for (const message of messages) {
            if (!this.isRateLimitingEnabledForTeam(message.teamId)) {
                continue
            }
            const currentCost = teamCosts.get(message.teamId) ?? 0
            // Cost is in KB (uncompressed bytes / 1000)
            const costKb = bytesToKb(message.bytesUncompressed)
            teamCosts.set(message.teamId, currentCost + costKb)

            // Store the timestamp for this team (use the first message's timestamp)
            if (!teamTimestamps.has(message.teamId)) {
                teamTimestamps.set(message.teamId, this.getTimestampFromMessage(message))
            }
        }

        // Check rate limits for all teams
        const rateLimitResults = await this.rateLimitMany(
            Array.from(teamCosts.entries()).map(([teamId, cost]) => [
                teamId.toString(),
                cost,
                teamTimestamps.get(teamId) ?? msToSeconds(Date.now()),
            ])
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
            const messageKb = bytesToKb(message.bytesUncompressed)

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
