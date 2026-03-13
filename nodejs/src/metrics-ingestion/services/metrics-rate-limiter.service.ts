import { Histogram } from 'prom-client'

import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

import { MetricsIngestionConsumerConfig } from '../config'
import { MetricsIngestionMessage } from '../types'

const msToSeconds = (ms: number): number => Math.round(ms / 1000)
const bytesToKb = (bytes: number): number => Math.ceil(bytes / 1000)

export const metricsMessageLagHistogram = new Histogram({
    name: 'metrics_rate_limiter_message_lag_seconds',
    help: 'Lag between message observed timestamp and wall clock time (seconds)',
    buckets: [-60, 0, 1, 5, 10, 30, 60, 300, 600, 1800, 3600],
})

export type MetricsRateLimiterConfig = Pick<
    MetricsIngestionConsumerConfig,
    | 'METRICS_LIMITER_TEAM_BUCKET_SIZE_KB'
    | 'METRICS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND'
    | 'METRICS_LIMITER_DISABLED_FOR_TEAMS'
    | 'METRICS_LIMITER_ENABLED_TEAMS'
    | 'METRICS_LIMITER_BUCKET_SIZE_KB'
    | 'METRICS_LIMITER_REFILL_RATE_KB_PER_SECOND'
    | 'METRICS_LIMITER_TTL_SECONDS'
>

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/metrics-rate-limiter' : '@posthog/metrics-rate-limiter'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`

export type MetricsRateLimit = {
    tokensBefore: number
    tokensAfter: number
    isRateLimited: boolean
}

export type FilteredMessages = {
    allowed: MetricsIngestionMessage[]
    dropped: MetricsIngestionMessage[]
}

export class MetricsRateLimiterService {
    private teamBucketSizes: Map<number, number>
    private teamRefillRates: Map<number, number>
    private disabledTeamIds: Set<number> | '*' | null
    private enabledTeamIds: Set<number> | '*' | null

    constructor(
        private config: MetricsRateLimiterConfig,
        private redis: RedisV2
    ) {
        this.teamBucketSizes = this.parseTeamConfig(config.METRICS_LIMITER_TEAM_BUCKET_SIZE_KB)
        this.teamRefillRates = this.parseTeamConfig(config.METRICS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND)
        this.disabledTeamIds = this.parseTeamIdList(config.METRICS_LIMITER_DISABLED_FOR_TEAMS)
        this.enabledTeamIds = this.parseTeamIdList(config.METRICS_LIMITER_ENABLED_TEAMS)
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
            this.teamBucketSizes.get(teamId) ?? this.config.METRICS_LIMITER_BUCKET_SIZE_KB,
            this.teamRefillRates.get(teamId) ?? this.config.METRICS_LIMITER_REFILL_RATE_KB_PER_SECOND,
            this.config.METRICS_LIMITER_TTL_SECONDS,
        ]
    }

    private getHeaderValue(headers: any[] | undefined, key: string): string | undefined {
        if (!headers || !Array.isArray(headers)) {
            return undefined
        }

        for (const header of headers) {
            if (header[key]) {
                return Buffer.from(header[key]).toString('utf8')
            }
        }
        return undefined
    }

    private getTimestampFromMessage(message: MetricsIngestionMessage): number {
        const createdAtHeader = this.getHeaderValue(message.message.headers, 'created_at')
        if (createdAtHeader) {
            const timestamp = Date.parse(createdAtHeader)
            if (!isNaN(timestamp)) {
                return msToSeconds(timestamp)
            }
        }
        return msToSeconds(Date.now())
    }

    public async rateLimitMany(idCosts: [string, number, number][]): Promise<[string, MetricsRateLimit][]> {
        const res = await this.redis.usePipeline({ name: 'metrics-rate-limiter', failOpen: true }, (pipeline) => {
            idCosts.forEach(([id, cost, nowSeconds]) => {
                pipeline.checkRateLimitV2(...this.rateLimitArgs(id, cost, nowSeconds))
            })
        })

        if (!res) {
            throw new Error('Failed to rate limit')
        }

        return idCosts.map(([id, ,], index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const tokensBefore = Number(tokenRes[1]?.[0] ?? this.config.METRICS_LIMITER_BUCKET_SIZE_KB)
            const tokensAfter = Number(tokenRes[1]?.[1] ?? this.config.METRICS_LIMITER_BUCKET_SIZE_KB)
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

    public async filterMessages(messages: MetricsIngestionMessage[]): Promise<FilteredMessages> {
        const teamCosts = new Map<number, number>()
        const teamOldestTimestamps = new Map<number, number>()

        for (const message of messages) {
            const messageTimestamp = this.getTimestampFromMessage(message)

            const existing = teamOldestTimestamps.get(message.teamId)
            if (existing === undefined || messageTimestamp < existing) {
                teamOldestTimestamps.set(message.teamId, messageTimestamp)
            }

            if (!this.isRateLimitingEnabledForTeam(message.teamId)) {
                continue
            }
            const currentCost = teamCosts.get(message.teamId) ?? 0
            const costKb = bytesToKb(message.bytesUncompressed)
            teamCosts.set(message.teamId, currentCost + costKb)
        }

        const nowSeconds = msToSeconds(Date.now())
        for (const [, timestamp] of teamOldestTimestamps) {
            metricsMessageLagHistogram.observe(nowSeconds - timestamp)
        }

        const rateLimitResults = await this.rateLimitMany(
            Array.from(teamCosts.entries()).map(([teamId, cost]) => [
                teamId.toString(),
                cost,
                teamOldestTimestamps.get(teamId) ?? msToSeconds(Date.now()),
            ])
        )

        const teamLimits = new Map<number, { tokensBefore: number; tokensAfter: number; isRateLimited: boolean }>()
        for (const [teamIdStr, result] of rateLimitResults) {
            teamLimits.set(parseInt(teamIdStr, 10), result)
        }

        const allowed: MetricsIngestionMessage[] = []
        const dropped: MetricsIngestionMessage[] = []
        const teamKbUsed = new Map<number, number>()

        for (const message of messages) {
            const limit = teamLimits.get(message.teamId)
            if (!limit) {
                allowed.push(message)
                continue
            }

            const kbUsed = teamKbUsed.get(message.teamId) ?? 0
            const availableKb = limit.tokensBefore
            const messageKb = bytesToKb(message.bytesUncompressed)

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
