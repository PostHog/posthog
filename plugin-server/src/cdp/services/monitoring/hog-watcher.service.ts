import { Counter } from 'prom-client'

import { logger } from '~/utils/logger'
import { captureTeamEvent } from '~/utils/posthog'

import { Hub } from '../../../types'
import { CdpRedis } from '../../redis'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionTiming,
    HogFunctionType,
} from '../../types'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-watcher-2' : '@posthog/hog-watcher-2'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/tokens`
const REDIS_KEY_STATE = `${BASE_REDIS_KEY}/state`
const REDIS_KEY_STATE_LOCK = `${BASE_REDIS_KEY}/state-lock`

export enum HogWatcherState {
    healthy = 1,
    degraded = 2,
    disabled = 3,
}

export type HogWatcherFunctionState = {
    tokens: number
    state: HogWatcherState
}

export const hogFunctionStateChange = new Counter({
    name: 'cdp_hog_function_state_change',
    help: 'Number of times a transformation state changed',
    labelNames: ['state', 'kind'],
})

type HogFunctionTimingCost = {
    lowerBound: number
    upperBound: number
    cost: number
}

type HogFunctionTimingCosts = Partial<Record<HogFunctionTiming['kind'], HogFunctionTimingCost>>

// Check if the result is of type CyclotronJobInvocationHogFunction
export const isHogFunctionResult = (
    result: CyclotronJobInvocationResult
): result is CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    return 'hogFunction' in result.invocation
}

type PipelineResults = [Error | null, any][]

const getPipelineResults = (res: PipelineResults, index: number, numOperations: number) => {
    // pipeline results are just a big array of operation results so we need to slice out the correct parts
    return res.slice(index * numOperations, index * numOperations + numOperations)
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

    private async onStateChange({
        hogFunction,
        state,
        previousState,
    }: {
        hogFunction: HogFunctionType
        state: HogWatcherState
        previousState: HogWatcherState
    }) {
        const team = await this.hub.teamManager.getTeam(hogFunction.team_id)

        logger.info('[HogWatcherService] onStateChange', {
            hogFunctionId: hogFunction.id,
            hogFunctionName: hogFunction.name,
            state,
            previousState,
        })

        if (team && process.env.CDP_HOG_WATCHER_2_CAPTURE_ENABLED === 'true') {
            captureTeamEvent(team, 'hog_function_state_change', {
                hog_function_id: hogFunction.id,
                hog_function_type: hogFunction.type,
                hog_function_name: hogFunction.name,
                hog_function_template_id: hogFunction.template_id,
                state: HogWatcherState[state], // Convert numeric state to readable string
                previous_state: HogWatcherState[previousState], // Convert numeric state to readable string
            })
        }
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

    public calculateNewState(tokens: number): HogWatcherState {
        const rating = tokens / this.hub.CDP_WATCHER_BUCKET_SIZE

        if (rating < 0 && this.hub.CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS) {
            return HogWatcherState.disabled
        }
        if (rating <= this.hub.CDP_WATCHER_THRESHOLD_DEGRADED) {
            return HogWatcherState.degraded
        }

        return HogWatcherState.healthy
    }

    public async getPersistedStates(
        ids: HogFunctionType['id'][]
    ): Promise<Record<HogFunctionType['id'], HogWatcherFunctionState>> {
        const idsSet = new Set(ids)

        const res = await this.redis.usePipeline({ name: 'getStates' }, (pipeline) => {
            for (const id of idsSet) {
                pipeline.checkRateLimit(...this.rateLimitArgs(id, 0))
                pipeline.get(`${REDIS_KEY_STATE}/${id}`)
            }
        })

        return Array.from(idsSet).reduce((acc, id, index) => {
            const resIndex = index * 2
            const tokens = res ? res[resIndex][1] : undefined
            const state = res ? res[resIndex + 1][1] : undefined

            acc[id] = {
                state: state ? Number(state) : HogWatcherState.healthy,
                tokens: tokens ?? this.hub.CDP_WATCHER_BUCKET_SIZE,
            }

            return acc
        }, {} as Record<HogFunctionType['id'], HogWatcherFunctionState>)
    }

    public async getPersistedState(id: HogFunctionType['id']): Promise<HogWatcherFunctionState> {
        const res = await this.getPersistedStates([id])
        return res[id]
    }

    public async getAllFunctionStates(): Promise<Record<HogFunctionType['id'], HogWatcherFunctionState>> {
        // Scan all state keys in Redis
        const stateKeys = await this.redis.useClient({ name: 'scanStates' }, async (client) => {
            const keys: string[] = []
            let cursor = '0'

            do {
                const [newCursor, batch] = await client.scan(cursor, 'MATCH', `${REDIS_KEY_STATE}/*`, 'COUNT', 500)
                cursor = newCursor
                keys.push(...batch)
            } while (cursor !== '0')

            return keys
        })

        if (!stateKeys || stateKeys.length === 0) {
            return {}
        }

        // Extract function IDs from the keys
        const functionIds = stateKeys.map((key: string) => key.replace(`${REDIS_KEY_STATE}/`, ''))

        // Get states for all found function IDs
        return await this.getPersistedStates(functionIds)
    }

    public async clearLock(id: HogFunctionType['id']): Promise<void> {
        await this.redis.usePipeline({ name: 'clearLock' }, (pipeline) => {
            pipeline.del(`${REDIS_KEY_STATE_LOCK}/${id}`)
        })
    }

    public async doStageChanges(
        changes: [HogFunctionType, HogWatcherState][],
        forceReset: boolean = false
    ): Promise<void> {
        logger.info('[HogWatcherService] Performing state changes', { changes, forceReset })
        const res = await this.redis.usePipeline({ name: 'forceStateChange' }, (pipeline) => {
            for (const [hogFunction, state] of changes) {
                const id = hogFunction.id
                const newScore =
                    state === HogWatcherState.healthy
                        ? this.hub.CDP_WATCHER_BUCKET_SIZE
                        : state === HogWatcherState.degraded
                        ? this.hub.CDP_WATCHER_BUCKET_SIZE * this.hub.CDP_WATCHER_THRESHOLD_DEGRADED
                        : 0

                const nowSeconds = Math.round(Date.now() / 1000)

                pipeline.getset(`${REDIS_KEY_STATE}/${id}`, state) // Set the state
                pipeline.setex(`${REDIS_KEY_STATE_LOCK}/${id}`, this.hub.CDP_WATCHER_STATE_LOCK_TTL, '1') // Set the lock
                if (forceReset) {
                    pipeline.hset(`${REDIS_KEY_TOKENS}/${id}`, 'pool', newScore)
                    pipeline.hset(`${REDIS_KEY_TOKENS}/${id}`, 'ts', nowSeconds)
                }
            }
        })

        if (!res) {
            return
        }

        const numOperations = forceReset ? 4 : 2

        await Promise.all(
            changes.map(async ([hogFunction, state], index) => {
                const [stateResult] = getPipelineResults(res, index, numOperations)
                const previousState = Number(stateResult[1] ?? HogWatcherState.healthy)
                if (previousState !== state) {
                    await this.onStateChange({
                        hogFunction,
                        state,
                        previousState,
                    })
                }
            })
        )
    }

    public async forceStateChange(hogFunction: HogFunctionType, state: HogWatcherState): Promise<void> {
        await this.doStageChanges([[hogFunction, state]])
    }

    public async observeResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        if (process.env.CDP_HOG_WATCHER_2_ENABLED !== 'true') {
            return
        }

        const functionCosts: Record<
            CyclotronJobInvocation['functionId'],
            {
                hogFunction?: HogFunctionType
                functionId: CyclotronJobInvocation['functionId']
                cost: number
            }
        > = {}

        results.forEach((result) => {
            if (!isHogFunctionResult(result)) {
                return
            }

            const functionCost = functionCosts[result.invocation.functionId] ?? {
                functionId: result.invocation.functionId,
                cost: 0,
                hogFunction: result.invocation.hogFunction,
            }

            if (result.finished) {
                // Process each timing entry individually instead of totaling them
                for (const timing of result.invocation.state.timings) {
                    const costConfig = this.costsMapping[timing.kind]
                    if (costConfig) {
                        const ratio =
                            Math.max(timing.duration_ms - costConfig.lowerBound, 0) /
                            (costConfig.upperBound - costConfig.lowerBound)
                        functionCost.cost += Math.round(costConfig.cost * ratio)
                    }
                }
            }

            functionCosts[result.invocation.functionId] = functionCost
        })

        // We apply the costs and return the existing states so we can calculate those that need a state change
        const res = await this.redis.usePipeline({ name: 'updateRateLimits' }, (pipeline) => {
            for (const functionCost of Object.values(functionCosts)) {
                pipeline.get(`${REDIS_KEY_STATE}/${functionCost.functionId}`)
                pipeline.get(`${REDIS_KEY_STATE_LOCK}/${functionCost.functionId}`)
                pipeline.checkRateLimit(...this.rateLimitArgs(functionCost.functionId, functionCost.cost))
            }
        })

        if (!res) {
            return
        }

        await Promise.all(
            Object.values(functionCosts).map(async (functionCost, index) => {
                const [stateResult, lockResult, tokenResult] = getPipelineResults(res, index, 3)

                const currentState: HogWatcherState = Number(stateResult[1] ?? HogWatcherState.healthy)
                const tokens = Number(tokenResult[1] ?? this.hub.CDP_WATCHER_BUCKET_SIZE)
                const newState = this.calculateNewState(tokens)

                if (currentState !== newState) {
                    if (lockResult[1]) {
                        // We don't want to change the state of a function that is being locked (i.e. recently changed state)
                        return
                    }

                    if (currentState === HogWatcherState.disabled) {
                        // We never modify the state of a disabled function automatically
                        return
                    }

                    if (functionCost.hogFunction) {
                        await this.forceStateChange(functionCost.hogFunction, newState)
                    }
                }
            })
        )
    }
}
