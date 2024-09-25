import { Hub } from '../types'
import { now } from '../utils/now'
import { UUIDT } from '../utils/utils'
import { CdpRedis } from './redis'
import { HogFunctionInvocationResult, HogFunctionType } from './types'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-watcher' : '@posthog/hog-watcher'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`
const REDIS_KEY_DISABLED = `${BASE_REDIS_KEY}/disabled`
const REDIS_KEY_DISABLED_HISTORY = `${BASE_REDIS_KEY}/disabled_history`

export enum HogWatcherState {
    healthy = 1,
    degraded = 2,
    disabledForPeriod = 3,
    disabledIndefinitely = 4,
}

export type HogWatcherFunctionState = {
    state: HogWatcherState
    tokens: number
    rating: number
}

export class HogWatcher {
    constructor(private hub: Hub, private redis: CdpRedis) {}

    private async onStateChange(id: HogFunctionType['id'], state: HogWatcherState) {
        await this.hub.db.celeryApplyAsync('posthog.tasks.hog_function_state_transition', [id, state])
    }

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

    public tokensToFunctionState(tokens?: number | null, stateOverride?: HogWatcherState): HogWatcherFunctionState {
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

        const res = await this.redis.usePipeline({ name: 'getStates' }, (pipeline) => {
            for (const id of idsSet) {
                pipeline.checkRateLimit(...this.rateLimitArgs(id, 0))
                pipeline.get(`${REDIS_KEY_DISABLED}/${id}`)
                pipeline.ttl(`${REDIS_KEY_DISABLED}/${id}`)
            }
        })

        return Array.from(idsSet).reduce((acc, id, index) => {
            const resIndex = index * 3
            const tokens = res ? res[resIndex][1] : undefined
            const disabled = res ? res[resIndex + 1][1] : false
            const disabledTemporarily = disabled && res ? res[resIndex + 2][1] !== -1 : false

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
        await this.redis.usePipeline({ name: 'forceStateChange' }, (pipeline) => {
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
                pipeline.set(`${REDIS_KEY_DISABLED}/${id}`, '1', 'EX', this.hub.CDP_WATCHER_DISABLED_TEMPORARY_TTL)
            } else if (state === HogWatcherState.disabledIndefinitely) {
                pipeline.set(`${REDIS_KEY_DISABLED}/${id}`, '1')
            } else {
                pipeline.del(`${REDIS_KEY_DISABLED}/${id}`)
            }
        })

        await this.onStateChange(id, state)
    }

    public async observeResults(results: HogFunctionInvocationResult[]): Promise<void> {
        const costs: Record<HogFunctionType['id'], number> = {}

        results.forEach((result) => {
            let cost = (costs[result.invocation.hogFunction.id] = costs[result.invocation.hogFunction.id] || 0)

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

            costs[result.invocation.hogFunction.id] = cost
        })

        const res = await this.redis.usePipeline({ name: 'checkRateLimits' }, (pipeline) => {
            Object.entries(costs).forEach(([id, change]) => {
                pipeline.checkRateLimit(...this.rateLimitArgs(id, change))
            })
        })

        // TRICKY: the above part is straight forward - below is more complex as we do multiple calls to ensure
        // that we disable the function temporarily and eventually permanently. As this is only called when the function
        // transitions to a disabled state, it is not a performance concern.

        const disabledFunctionIds = Object.entries(costs)
            .filter((_, index) => (res ? res[index][1] <= 0 : false))
            .map(([id]) => id)

        if (disabledFunctionIds.length) {
            // Mark them all as disabled in redis

            const results = await this.redis.usePipeline({ name: 'markDisabled' }, (pipeline) => {
                disabledFunctionIds.forEach((id) => {
                    pipeline.set(
                        `${REDIS_KEY_DISABLED}/${id}`,
                        '1',
                        'EX',
                        this.hub.CDP_WATCHER_DISABLED_TEMPORARY_TTL,
                        'NX'
                    )
                })
            })

            const functionsTempDisabled = disabledFunctionIds.filter((_, index) =>
                results ? results[index][1] : false
            )

            if (!functionsTempDisabled.length) {
                return
            }

            // We store the history as a zset - we can then use it to determine if we should disable indefinitely
            const historyResults = await this.redis.usePipeline({ name: 'addTempDisabled' }, (pipeline) => {
                functionsTempDisabled.forEach((id) => {
                    const key = `${REDIS_KEY_DISABLED_HISTORY}/${id}`
                    pipeline.zadd(key, now(), new UUIDT().toString())
                    pipeline.zrange(key, 0, -1)
                    pipeline.expire(key, this.hub.CDP_WATCHER_TTL)
                })
            })

            const functionsToDisablePermanently = functionsTempDisabled.filter((_, index) => {
                const history = historyResults ? historyResults[index * 3 + 1][1] : []
                return history.length >= this.hub.CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT
            })

            if (functionsToDisablePermanently.length) {
                await this.redis.usePipeline({ name: 'disablePermanently' }, (pipeline) => {
                    functionsToDisablePermanently.forEach((id) => {
                        const key = `${REDIS_KEY_DISABLED}/${id}`
                        pipeline.set(key, '1')
                        pipeline.del(`${REDIS_KEY_DISABLED_HISTORY}/${id}`)
                    })
                })
            }

            // Finally track the results
            for (const id of functionsToDisablePermanently) {
                await this.onStateChange(id, HogWatcherState.disabledIndefinitely)
            }

            for (const id of functionsTempDisabled) {
                if (!functionsToDisablePermanently.includes(id)) {
                    await this.onStateChange(id, HogWatcherState.disabledForPeriod)
                }
            }
        }
    }
}
