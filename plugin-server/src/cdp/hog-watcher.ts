import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'

import { Hub } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { status } from '../utils/status'
import { HogFunctionInvocationResult, HogFunctionType } from './types'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-watcher' : '@posthog/hog-watcher'
const REDIS_KEY_SCORES = `${BASE_REDIS_KEY}/scores`
const REDIS_TIMEOUT_SECONDS = 5

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
    constructor(private hub: Hub) {}

    private async runRedis<T>(fn: (client: Redis) => Promise<T>): Promise<T | null> {
        // We want all of this to fail open in the issue of redis being unavailable - we'd rather have the function continue
        const client = await this.hub.redisPool.acquire()
        const timeout = timeoutGuard(
            `Redis call delayed. Waiting over ${REDIS_TIMEOUT_SECONDS} seconds.`,
            undefined,
            REDIS_TIMEOUT_SECONDS * 1000
        )
        try {
            return await fn(client)
        } catch (e) {
            status.error('HogWatcher Redis error', e)
            captureException(e)
            return null
        } finally {
            clearTimeout(timeout)
            await this.hub.redisPool.release(client)
        }
    }

    public scoreToState(score: number): HogWatcherState {
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
        const idsSet = new Set(ids)

        // TODO: Gracefully handle errors
        const states = await this.runRedis(async (client) => {
            const pipeline = client.pipeline()

            for (const id of idsSet) {
                pipeline.get(`${REDIS_KEY_SCORES}/${id}`)
            }

            return pipeline.exec()
        })

        return Array.from(idsSet).reduce((acc, id, index) => {
            const score = states ? Number(states[index][1]) : 0
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
        const res = await this.runRedis(async (client) => {
            const score = await client.get(`${REDIS_KEY_SCORES}/${id}`)
            return score
        })

        const score = Number(res ?? 0)

        return {
            state: this.scoreToState(score),
            score,
        }
    }

    public async forceStateChange(id: HogFunctionType['id'], state: HogWatcherState): Promise<void> {
        await this.runRedis(async (client) => {
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

        await this.runRedis(async (client) => {
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
