import { captureException } from '@sentry/node'
import { readFileSync } from 'fs'
import { Pipeline, Redis } from 'ioredis'
import path from 'path'

import { Hub } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { now } from '../utils/now'
import { status } from '../utils/status'
import { HogFunctionInvocationResult, HogFunctionType } from './types'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-watcher' : '@posthog/hog-watcher'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`
const REDIS_KEY_DISABLED = `${BASE_REDIS_KEY}/disabled`
const REDIS_TIMEOUT_SECONDS = 5

const LUA_TOKEN_BUCKET = readFileSync(path.join(__dirname, 'lua', 'token-bucket.lua')).toString()

export enum HogWatcherState {
    healthy = 1,
    degraded = 2,
    disabledForPeriod = 3,
    disabledIndefinitely = 4,
}

// const hogStateChangeCounter = new Counter({
//     name: 'cdp_hog_watcher_state_change',
//     help: 'An function was moved to a different state',
//     labelNames: ['state'],
// })

export type HogWatcherFunctionState = {
    state: HogWatcherState
    tokens: number
    rating: number
}

type WithCheckRateLimit<T> = {
    checkRateLimit: (key: string, now: number, cost: number, poolMax: number, fillRate: number, expiry: number) => T
}

type HogWatcherRedisClientPipeline = Pipeline & WithCheckRateLimit<number>

type HogWatcherRedisClient = Omit<Redis, 'pipeline'> &
    WithCheckRateLimit<Promise<number>> & {
        pipeline: () => HogWatcherRedisClientPipeline
    }

export class HogWatcher {
    constructor(private hub: Hub) {}

    private rateLimitArgs(id: HogFunctionType['id'], cost: number) {
        const nowSeconds = Math.round(now() / 1000)
        return [
            `${REDIS_KEY_TOKENS}/${id}`,
            nowSeconds,
            cost,
            this.hub.CDP_WATCHER_BUCKET_SIZE,
            this.hub.CDP_WATCHER_REFILL_RATE,
            this.hub.CDP_WATCHER_TTL,
        ] as const
    }

    private async runRedis<T>(fn: (client: HogWatcherRedisClient) => Promise<T>): Promise<T | null> {
        // We want all of this to fail open in the issue of redis being unavailable - we'd rather have the function continue
        const client = await this.hub.redisPool.acquire()

        client.defineCommand('checkRateLimit', {
            numberOfKeys: 1,
            lua: LUA_TOKEN_BUCKET,
        })

        const timeout = timeoutGuard(
            `Redis call delayed. Waiting over ${REDIS_TIMEOUT_SECONDS} seconds.`,
            undefined,
            REDIS_TIMEOUT_SECONDS * 1000
        )
        try {
            return await fn(client as HogWatcherRedisClient)
        } catch (e) {
            status.error('HogWatcher Redis error', e)
            captureException(e)
            return null
        } finally {
            clearTimeout(timeout)
            await this.hub.redisPool.release(client)
        }
    }

    public tokensToFunctionState(tokens?: number | null, stateOverride?: HogWatcherState): HogWatcherFunctionState {
        console.log(tokens, stateOverride)
        tokens = tokens ?? this.hub.CDP_WATCHER_BUCKET_SIZE
        const rating = tokens / this.hub.CDP_WATCHER_BUCKET_SIZE

        const state =
            stateOverride ??
            (rating >= this.hub.CDP_WATCHER_THRESHOLD_DEGRADED
                ? HogWatcherState.healthy
                : rating > 0
                ? HogWatcherState.degraded
                : HogWatcherState.disabledForPeriod)

        return { state, tokens, rating }
    }

    public async getStates(
        ids: HogFunctionType['id'][]
    ): Promise<Record<HogFunctionType['id'], HogWatcherFunctionState>> {
        const idsSet = new Set(ids)

        const res = await this.runRedis(async (client) => {
            const pipeline = client.pipeline()

            for (const id of idsSet) {
                pipeline.checkRateLimit(...this.rateLimitArgs(id, 0))
                pipeline.get(`${REDIS_KEY_DISABLED}/${id}`)
                pipeline.ttl(`${REDIS_KEY_DISABLED}/${id}`)
            }

            return pipeline.exec()
        })

        return Array.from(idsSet).reduce((acc, id, index) => {
            const resIndex = index * 3
            const tokens = res ? res[resIndex][1] : undefined
            const disabled = res ? res[resIndex + 1][1] : false
            const disabledTemporarily = disabled && res ? !!res[resIndex + 2][1] : false

            return {
                ...acc,
                [id]: this.tokensToFunctionState(
                    tokens,
                    disabled
                        ? disabledTemporarily
                            ? HogWatcherState.disabledForPeriod
                            : HogWatcherState.disabledIndefinitely
                        : undefined
                ),
            }
        }, {} as Record<HogFunctionType['id'], HogWatcherFunctionState>)
    }

    public async getState(id: HogFunctionType['id']): Promise<HogWatcherFunctionState> {
        const res = await this.getStates([id])
        return res[id]
    }

    public async forceStateChange(id: HogFunctionType['id'], state: HogWatcherState): Promise<void> {
        await this.runRedis(async (client) => {
            const pipeline = client.pipeline()

            const newScore =
                state === HogWatcherState.healthy
                    ? this.hub.CDP_WATCHER_BUCKET_SIZE
                    : state === HogWatcherState.degraded
                    ? this.hub.CDP_WATCHER_BUCKET_SIZE * this.hub.CDP_WATCHER_THRESHOLD_DEGRADED
                    : 0

            const nowSeconds = Math.round(now() / 1000)

            pipeline.hset(`${REDIS_KEY_TOKENS}/${id}`, 'pool', newScore)
            pipeline.hset(`${REDIS_KEY_TOKENS}/${id}`, 'ts', nowSeconds)

            if (state === HogWatcherState.disabledForPeriod) {
                pipeline.set(`${REDIS_KEY_DISABLED}/${id}`, '1', 'EX', this.hub.CDP_WATCHER_DISABLED_TTL)
            } else if (state === HogWatcherState.disabledIndefinitely) {
                pipeline.set(`${REDIS_KEY_DISABLED}/${id}`, '1')
            } else {
                pipeline.del(`${REDIS_KEY_DISABLED}/${id}`)
            }

            await pipeline.exec()
        })
    }

    public async observeResults(results: HogFunctionInvocationResult[]): Promise<void> {
        const costs: Record<HogFunctionType['id'], number> = {}

        results.forEach((result) => {
            let cost = (costs[result.invocation.hogFunctionId] = costs[result.invocation.hogFunctionId] || 0)

            if (result.finished) {
                // If it is finished we can calculate the score based off of the timings

                const totalDurationMs = result.invocation.timings.reduce((acc, timing) => acc + timing.duration_ms, 0)
                const lowerBound = this.hub.CDP_WATCHER_COST_TIMING_LOWER_MS
                const upperBound = this.hub.CDP_WATCHER_COST_TIMING_UPPER_MS
                const costTiming = this.hub.CDP_WATCHER_COST_TIMING
                const ratio = Math.max(totalDurationMs - lowerBound, 0) / (upperBound - lowerBound)

                cost += Math.round(costTiming * ratio)
            }

            if (result.error) {
                cost += this.hub.CDP_WATCHER_COST_ERROR
            }

            costs[result.invocation.hogFunctionId] = cost
        })

        const res = await this.runRedis(async (client) => {
            const pipeline = client.pipeline()

            Object.entries(costs).forEach(([id, change]) => {
                pipeline.checkRateLimit(...this.rateLimitArgs(id, change))
            })

            return await pipeline.exec()
        })

        const disabledFunctionIds = Object.entries(costs)
            .filter((_, index) => (res ? res[index][1] <= 0 : false))
            .map(([id]) => id)

        if (disabledFunctionIds.length) {
            // Mark them all as disabled in redis

            await this.runRedis(async (client) => {
                const pipeline = client.pipeline()

                disabledFunctionIds.forEach((id) => {
                    pipeline.set(`${REDIS_KEY_DISABLED}/${id}`, '1', 'EX', this.hub.CDP_WATCHER_DISABLED_TTL)
                })

                await pipeline.exec()
            })
        }
    }
}
