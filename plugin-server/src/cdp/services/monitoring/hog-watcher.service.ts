import { Counter, Histogram } from 'prom-client'

import { captureTeamEvent } from '~/utils/posthog'

import { Hub } from '../../../types'
import { UUIDT } from '../../../utils/utils'
import { CdpRedis } from '../../redis'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionTiming,
    HogFunctionType,
} from '../../types'

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

export const hogFunctionExecutionTimeSummary = new Histogram({
    name: 'cdp_hog_watcher_duration',
    help: 'Processing time of hog function execution by kind',
    labelNames: ['kind'],
})

export const hogFunctionStateChange = new Counter({
    name: 'hog_function_state_change',
    help: 'Number of times a transformation state changed',
    labelNames: ['state', 'kind'],
})

type HogFunctionTimingCost = {
    lowerBound: number
    upperBound: number
    cost: number
}

type HogFunctionTimingCosts = Partial<Record<HogFunctionTiming['kind'], HogFunctionTimingCost>>

// TODO: Future follow up - we should swap this to an API call or something.
// Having it as a celery task ID based on a file path is brittle and hard to test.
export const CELERY_TASK_ID = 'posthog.tasks.plugin_server.hog_function_state_transition'

// Check if the result is of type CyclotronJobInvocationHogFunction
export const isHogFunctionResult = (
    result: CyclotronJobInvocationResult
): result is CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    return 'hogFunction' in result.invocation
}

export class HogWatcherService {
    private costsMapping: HogFunctionTimingCosts

    constructor(private hub: Hub, private redis: CdpRedis) {
        this.costsMapping = {
            hog: {
                lowerBound: this.hub.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS,
                upperBound: this.hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                cost: this.hub.CDP_WATCHER_HOG_COST_TIMING,
            },
            async_function: {
                lowerBound: this.hub.CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS,
                upperBound: this.hub.CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS,
                cost: this.hub.CDP_WATCHER_ASYNC_COST_TIMING,
            },
        }

        for (const [kind, mapping] of Object.entries(this.costsMapping)) {
            if (mapping.lowerBound >= mapping.upperBound) {
                throw new Error(
                    `Lower bound for kind ${kind} of ${mapping.lowerBound}ms must be lower than upper bound of ${mapping.upperBound}ms. This is a configuration error.`
                )
            }
        }
    }

    private async onStateChange(hogFunction: HogFunctionType, state: HogWatcherState) {
        const team = await this.hub.teamManager.getTeam(hogFunction.team_id)
        if (team) {
            captureTeamEvent(team, 'hog_function_state_change', {
                hog_function_id: hogFunction.id,
                hog_function_type: hogFunction.type,
                hog_function_name: hogFunction.name,
                hog_function_template_id: hogFunction.template_id,
                state: HogWatcherState[state], // Convert numeric state to readable string
            })
        }
        await this.hub.celery.applyAsync(CELERY_TASK_ID, [hogFunction.id, state])
    }

    private rateLimitArgs(id: HogFunctionType['id'], cost: number) {
        const nowSeconds = Math.round(Date.now() / 1000)
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

            acc[id] = this.tokensToFunctionState(
                tokens,
                disabled
                    ? disabledTemporarily
                        ? HogWatcherState.disabledForPeriod
                        : HogWatcherState.disabledIndefinitely
                    : undefined
            )

            return acc
        }, {} as Record<HogFunctionType['id'], HogWatcherFunctionState>)
    }

    public async getState(id: HogFunctionType['id']): Promise<HogWatcherFunctionState> {
        const res = await this.getStates([id])
        return res[id]
    }

    public async forceStateChange(hogFunction: HogFunctionType, state: HogWatcherState): Promise<void> {
        const id = hogFunction.id
        await this.redis.usePipeline({ name: 'forceStateChange' }, (pipeline) => {
            const newScore =
                state === HogWatcherState.healthy
                    ? this.hub.CDP_WATCHER_BUCKET_SIZE
                    : state === HogWatcherState.degraded
                    ? this.hub.CDP_WATCHER_BUCKET_SIZE * this.hub.CDP_WATCHER_THRESHOLD_DEGRADED
                    : 0

            const nowSeconds = Math.round(Date.now() / 1000)

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
        await this.onStateChange(hogFunction, state)
    }

    public async observeResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        // NOTE: Currently we only monitor hog code timings. We will have a separate config for async functions

        const costs: Record<CyclotronJobInvocation['functionId'], number> = {}
        // Create a map to store the function types
        const hogFunctionsById: Record<CyclotronJobInvocation['functionId'], HogFunctionType> = {}

        results.forEach((result) => {
            if (!isHogFunctionResult(result)) {
                return
            }

            let cost = (costs[result.invocation.functionId] = costs[result.invocation.functionId] || 0)
            hogFunctionsById[result.invocation.functionId] = result.invocation.hogFunction

            if (result.finished) {
                // Process each timing entry individually instead of totaling them
                for (const timing of result.invocation.state.timings) {
                    // Record metrics for this timing entry
                    hogFunctionExecutionTimeSummary.labels({ kind: timing.kind }).observe(timing.duration_ms)

                    const costConfig = this.costsMapping[timing.kind]
                    if (costConfig) {
                        const ratio =
                            Math.max(timing.duration_ms - costConfig.lowerBound, 0) /
                            (costConfig.upperBound - costConfig.lowerBound)
                        cost += Math.round(costConfig.cost * ratio)
                    }
                }
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
                    pipeline.zadd(key, Date.now(), new UUIDT().toString())
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
                hogFunctionStateChange
                    .labels({
                        state: 'disabled_indefinitely',
                        kind: hogFunctionsById[id].type,
                    })
                    .inc()
                await this.onStateChange(hogFunctionsById[id], HogWatcherState.disabledIndefinitely)
            }

            for (const id of functionsTempDisabled) {
                if (!functionsToDisablePermanently.includes(id)) {
                    hogFunctionStateChange
                        .labels({
                            state: 'disabled_for_period',
                            kind: hogFunctionsById[id].type,
                        })
                        .inc()
                    await this.onStateChange(hogFunctionsById[id], HogWatcherState.disabledForPeriod)
                }
            }
        }
    }
}
