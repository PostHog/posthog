import { readFileSync } from 'fs'
import path from 'path'

import { Hub } from '../types'
import { HogFunctionInvocationResult, HogFunctionType } from './types'
import { runRedis } from './utils'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-watcher' : '@posthog/hog-watcher'
const REDIS_KEY_SCORES = `${BASE_REDIS_KEY}/scores`

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
    score: number
}

export class HogWatcher {
    setupPromise?: Promise<void>

    constructor(private hub: Hub) {}

    private setup(): Promise<void> {
        if (!this.setupPromise) {
            this.setupPromise = runRedis(this.hub.redisPool, 'init', (client) => {
                client.defineCommand('consumeTokenBucket', {
                    numberOfKeys: 2,
                    // The lua here is needed to ensure that we can do things atomically without multiple round trips
                    // It takes arguments for the max bucket size, the rate at which the bucket refills over time.

                    // When we call it, we pass in the cost. Unlike normal rate limiting a cost is only incurred if something went wrong

                    // It returns the numnber

                    lua: `
                        local key = KEYS[1]
                        local bucket_size = tonumber(ARGV[1])
                        local refill_rate = tonumber(ARGV[2])
                        local cost = tonumber(ARGV[3])

                        local current = tonumber(redis.call('get', key) or 0)
                        local refill_amount = math.max(0, (current - refill_rate) + cost)

                        if refill_amount > bucket_size then
                            return 0
                        end

                        redis.call('set', key, refill_amount)
                        return 1
                    `,
                })
                return Promise.resolve()
            })
        }

        return this.setupPromise
    }

    public scoreToState(score: number): HogWatcherState {
        // TODO: Add check for permanent disabled

        if (score <= this.hub.CDP_WATCHER_THRESHOLD_DISABLED) {
            return HogWatcherState.disabledForPeriod
        } else if (score <= this.hub.CDP_WATCHER_THRESHOLD_DEGRADED) {
            return HogWatcherState.degraded
        }

        return HogWatcherState.healthy
    }

    public async getStates(
        ids: HogFunctionType['id'][]
    ): Promise<Record<HogFunctionType['id'], HogWatcherFunctionState>> {
        await this.setup()
        const idsSet = new Set(ids)

        // TODO: Gracefully handle errors
        const states = await runRedis(this.hub.redisPool, 'getStates', async (client) => {
            const pipeline = client.pipeline()

            for (const id of idsSet) {
                pipeline.get(`${REDIS_KEY_SCORES}/${id}`)
            }

            return pipeline.exec()
        })

        return Array.from(idsSet).reduce((acc, id, index) => {
            const score = Number(states[index][1])
            return {
                ...acc,
                [id]: {
                    state: this.scoreToState(score),
                    score,
                },
            }
        }, {} as Record<HogFunctionType['id'], HogWatcherFunctionState>)
    }

    public async getState(id: HogFunctionType['id']): Promise<HogWatcherFunctionState> {
        await this.setup()
        const res = await runRedis(this.hub.redisPool, 'getState', async (client) => {
            const score = await client.get(`${REDIS_KEY_SCORES}/${id}`)
            return score
        })

        const score = Number(res)

        return {
            state: this.scoreToState(score),
            score,
        }
    }

    public async forceStateChange(id: HogFunctionType['id'], state: HogWatcherState): Promise<void> {
        await this.setup()
        await runRedis(this.hub.redisPool, 'forceStateChange', async (client) => {
            const pipeline = client.pipeline()

            const newScore =
                state === HogWatcherState.healthy
                    ? 0
                    : state === HogWatcherState.degraded
                    ? this.hub.CDP_WATCHER_THRESHOLD_DEGRADED
                    : this.hub.CDP_WATCHER_THRESHOLD_DISABLED

            pipeline.set(`${REDIS_KEY_SCORES}/${id}`, newScore)
            pipeline.expire(`${REDIS_KEY_SCORES}/${id}`, this.hub.CDP_WATCHER_TTL)

            await pipeline.exec()
        })
    }

    public async observeResults(results: HogFunctionInvocationResult[]): Promise<void> {
        await this.setup()
        const changes: Record<HogFunctionType['id'], number> = {}

        results.forEach((result) => {
            let change = (changes[result.invocation.hogFunctionId] = changes[result.invocation.hogFunctionId] || 0)

            if (result.finished) {
                // If it is finished we can calculate the score based off of the timings

                const totalDurationMs = result.invocation.timings.reduce((acc, timing) => acc + timing.duration_ms, 0)

                const lowerBound = this.hub.CDP_WATCHER_SCORE_TIMING_LOWER
                const upperBound = this.hub.CDP_WATCHER_SCORE_TIMING_UPPER
                const scoreSuccess = this.hub.CDP_WATCHER_SCORE_SUCCESS
                const ratio = Math.max(totalDurationMs - lowerBound, 0) / (upperBound - lowerBound)

                change += Math.round(scoreSuccess - scoreSuccess * ratio)
            }

            if (result.error) {
                change += this.hub.CDP_WATCHER_SCORE_ERROR // Errors incur medium penalties
            }

            changes[result.invocation.hogFunctionId] = change
        })

        // TODO: Gracefully handle errors
        await runRedis(this.hub.redisPool, 'stop', async (client) => {
            let pipeline = client.pipeline()

            const changeEntries = Object.entries(changes)

            changeEntries.forEach(([id, change]) => {
                pipeline.incrby(`${REDIS_KEY_SCORES}/${id}`, change)
                pipeline.expire(`${REDIS_KEY_SCORES}/${id}`, this.hub.CDP_WATCHER_TTL)
            })

            const results = await pipeline.exec()

            pipeline = client.pipeline()

            changeEntries.forEach(([id], index) => {
                const [err, value] = results[index * 2]
                let override: number | null = null

                if (err) {
                    // If there was an error, we can just skip
                } else if (value < this.hub.CDP_WATCHER_THRESHOLD_DISABLED) {
                    override = this.hub.CDP_WATCHER_THRESHOLD_DISABLED
                } else if (value > this.hub.CDP_WATCHER_THRESHOLD_HEALTHY) {
                    override = this.hub.CDP_WATCHER_THRESHOLD_HEALTHY
                }

                if (override !== null) {
                    pipeline.set(`${REDIS_KEY_SCORES}/${id}`, override)
                    pipeline.expire(`${REDIS_KEY_SCORES}/${id}`, this.hub.CDP_WATCHER_TTL)
                }
            })

            await pipeline.exec()
        })
    }
}
