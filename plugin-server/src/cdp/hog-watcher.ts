import { Redis } from 'ioredis'
import { randomUUID } from 'node:crypto'

import { Hub, RedisPool } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { now } from '../utils/now'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult, HogFunctionType } from './types'

/**
 * General approach:
 *
 * We want to detect when a function has gone rogue and gradually stop it from running.
 * We calculate its "rating" based on how many times it has succeeded and failed.
 *
 * If the rating falls too low, over a period of time we want to move it to the overflow queue as a first step to ensure it doesn't hog resources.
 * If it stays too low, we eventually want to disable it for a period of time.
 *
 * If it _still_ behaves poorly after this time period, we want to disable it indefinitely.
 * This can be represented as a state for the function - 1. Healthy, 2. Overflowed, 3. Disabled for a period, 4. Disabled indefinitely.
 *
 * To be able to do this right we need to store an array of values for the functions rating over time that represent the last say 10 minutes.
 * In addition we need to record the last N states of the function so that we can decide to disable it indefinitely if it has spent too much time in state 3
 * State 1:
 *   - If the rating average over the time period is below 0.5, move to state 2.
 * State 2:
 *   - If the rating average over the time period is above 0.5, move to state 1.
 *   - If the rating average over the time period is below 0.5 AND the function was in state 3 for more than N of the last states, move to state 4.
 *   - If the rating average over the time period is below 0.5, move to state 3.
 *
 * State 3:
 *   - The function is disabled for a period of time (perhaps the same as the measuring period).
 *   - Once it is out of this masked period, move to state 2.
 * State 4:
 *   - The function is disabled and requires manual intervention
 */

export enum HogWatcherState {
    healthy = 1,
    overflowed = 2,
    disabledForPeriod = 3,
    disabledIndefinitely = 4,
}

export type HogWatcherStatePeriod = {
    timestamp: number
    state: HogWatcherState
}

export type HogWatcherObservationPeriod = {
    timestamp: number
    successes: number
    failures: number
    asyncFunctionFailures: number
    asyncFunctionSuccesses: number
}

export type HogWatcherSummary = {
    state: HogWatcherState
    rating: number
    states: HogWatcherStatePeriod[]
    observations: HogWatcherObservationPeriod[]
}

export type EmittedHogWatcherObservations = {
    instanceId: string
    observations: {
        id: HogFunctionType['id']
        observation: HogWatcherObservationPeriod
    }[]
}

export type EmittedHogWatcherStates = {
    instanceId: string
    states: {
        id: HogFunctionType['id']
        state: HogWatcherStatePeriod
    }[]
}

const REDIS_TIMEOUT_SECONDS = 5

export const OBSERVATION_PERIOD = 10000 // Adjust this for more or less granular checking
export const EVALUATION_PERIOD = OBSERVATION_PERIOD * 100 // Essentially how many periods to keep in memory
export const DISABLED_PERIOD = 1000 * 60 * 10 // 10 minutes
export const MAX_RECORDED_STATES = 10
export const MAX_ALLOWED_TEMPORARY_DISABLES = MAX_RECORDED_STATES / 2
export const MIN_OBSERVATIONS = 3

export const OVERFLOW_THRESHOLD = 0.8
export const DISABLE_THRESHOLD = 0.5

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-watcher' : '@posthog/hog-watcher'

const redisKeyObservations = (id: HogFunctionType['id']) => `${BASE_REDIS_KEY}/observations/${id}`
const redisKeyStates = (id: HogFunctionType['id']) => `${BASE_REDIS_KEY}/states/${id}`

export const calculateRating = (observation: HogWatcherObservationPeriod): number => {
    // Rating is from 0 to 1
    // 1 - Function is working perfectly
    // 0 - Function is not working at all

    const totalInvocations = observation.successes + observation.failures
    const totalAsyncInvocations = observation.asyncFunctionSuccesses + observation.asyncFunctionFailures
    const successRate = totalInvocations ? observation.successes / totalInvocations : 1
    const asyncSuccessRate = totalAsyncInvocations ? observation.asyncFunctionSuccesses / totalAsyncInvocations : 1

    return Math.min(1, successRate, asyncSuccessRate)
}

export const getAverageRating = (observations: HogWatcherObservationPeriod[]): number => {
    return observations.length ? observations.reduce((acc, x) => acc + calculateRating(x), 0) / observations.length : 1
}

export const periodTimestamp = (timestamp?: number): number => {
    // Returns the timestamp but rounded to the nearest period (e.g. 1 minute)
    return Math.floor((timestamp ?? now()) / OBSERVATION_PERIOD) * OBSERVATION_PERIOD
}

export const deriveCurrentState = (
    _observations: HogWatcherObservationPeriod[],
    states: HogWatcherStatePeriod[]
): HogWatcherState => {
    const period = periodTimestamp()
    // TODO: Prune old observations and states
    // Observations are pruned by age
    const observations = _observations.filter((x) => {
        // Filter out observations that are older than the evaluation period
        // and also that are the same as the last period (we wan to allow for
        // a settlement period for each worker to update their states)
        return x.timestamp >= period - EVALUATION_PERIOD && x.timestamp !== period
    })

    // States are pruned by a max length rather than time
    if (states.length > MAX_RECORDED_STATES) {
        states = states.slice(states.length - MAX_RECORDED_STATES)
    }

    const currentState = states[states.length - 1] ?? {
        timestamp: now(),
        state: HogWatcherState.healthy,
    }

    if (currentState.state === HogWatcherState.disabledIndefinitely) {
        return HogWatcherState.disabledIndefinitely
    }

    // If we are disabled for a period then we only check if it should no longer be disabled
    if (currentState.state === HogWatcherState.disabledForPeriod) {
        if (now() - currentState.timestamp > DISABLED_PERIOD) {
            return HogWatcherState.overflowed
        }
    }

    if (observations.length < MIN_OBSERVATIONS) {
        // We need to give the function a chance to run before we can evaluate it
        return currentState.state
    }

    const averageRating = getAverageRating(observations)

    if (currentState.state === HogWatcherState.overflowed) {
        if (averageRating > OVERFLOW_THRESHOLD) {
            // The function is behaving well again - move it to healthy
            return HogWatcherState.healthy
        }

        if (averageRating < DISABLE_THRESHOLD) {
            // The function is behaving worse than overflow can accept - disable it
            const disabledStates = states.filter((x) => x.state === HogWatcherState.disabledForPeriod)

            if (disabledStates.length >= MAX_ALLOWED_TEMPORARY_DISABLES) {
                // this function has spent half of the time in temporary disabled so we disable it indefinitely
                return HogWatcherState.disabledIndefinitely
            }

            return HogWatcherState.disabledForPeriod
        }
    }

    if (currentState.state === HogWatcherState.healthy) {
        if (averageRating < OVERFLOW_THRESHOLD) {
            return HogWatcherState.overflowed
        }
    }

    return currentState.state
}

const mergeObservations = (observations: HogWatcherObservationPeriod[]): HogWatcherObservationPeriod[] => {
    const merged: Record<number, HogWatcherObservationPeriod> = {}

    observations.forEach((observation) => {
        const period = periodTimestamp(observation.timestamp)
        merged[period] = merged[period] ?? {
            timestamp: period,
            successes: 0,
            failures: 0,
            asyncFunctionFailures: 0,
            asyncFunctionSuccesses: 0,
        }

        merged[period].successes += observation.successes
        merged[period].failures += observation.failures
        merged[period].asyncFunctionFailures += observation.asyncFunctionFailures
        merged[period].asyncFunctionSuccesses += observation.asyncFunctionSuccesses
    })

    return Object.values(merged).sort((a, b) => a.timestamp - b.timestamp)
}

async function runRedis<T>(redisPool: RedisPool, description: string, fn: (client: Redis) => Promise<T>): Promise<T> {
    const client = await redisPool.acquire()
    const timeout = timeoutGuard(
        `${description} delayed. Waiting over ${REDIS_TIMEOUT_SECONDS} seconds.`,
        undefined,
        REDIS_TIMEOUT_SECONDS * 1000
    )
    try {
        return await fn(client)
    } finally {
        clearTimeout(timeout)
        await redisPool.release(client)
    }
}

export class HogWatcherActiveObservations {
    observations: Record<HogFunctionType['id'], HogWatcherObservationPeriod> = {}

    constructor() {}

    private addObservations(
        id: HogFunctionType['id'],
        incrs: Pick<
            Partial<HogWatcherObservationPeriod>,
            'successes' | 'failures' | 'asyncFunctionFailures' | 'asyncFunctionSuccesses'
        >
    ): void {
        if (!this.observations[id]) {
            this.observations[id] = {
                timestamp: periodTimestamp(),
                successes: 0,
                failures: 0,
                asyncFunctionFailures: 0,
                asyncFunctionSuccesses: 0,
            }
        }

        this.observations[id].successes += incrs.successes ?? 0
        this.observations[id].failures += incrs.failures ?? 0
        this.observations[id].asyncFunctionFailures += incrs.asyncFunctionFailures ?? 0
        this.observations[id].asyncFunctionSuccesses += incrs.asyncFunctionSuccesses ?? 0
    }

    observeResults(results: HogFunctionInvocationResult[]) {
        results.forEach((result) =>
            this.addObservations(result.hogFunctionId, {
                successes: result.finished ? 1 : 0,
                failures: result.error ? 1 : 0,
            })
        )
    }

    observeAsyncFunctionResponses(responses: HogFunctionInvocationAsyncResponse[]) {
        // NOTE: This probably wants to be done using the response status instead :thinking:
        responses.forEach((response) =>
            this.addObservations(response.hogFunctionId, {
                asyncFunctionSuccesses: response.error ? 0 : 1,
                asyncFunctionFailures: response.error ? 1 : 0,
            })
        )
    }
}

export class HogWatcher {
    public readonly currentObservations = new HogWatcherActiveObservations()
    public readonly states: Record<HogFunctionType['id'], HogWatcherStatePeriod[]> = {}
    public readonly observations: Record<HogFunctionType['id'], HogWatcherObservationPeriod[]> = {}
    public readonly summaries: Record<HogFunctionType['id'], HogWatcherSummary> = {}

    // Only the leader should be able to write to the states
    private isLeader: boolean = false
    private pubSub: PubSub
    private instanceId: string
    private interval?: NodeJS.Timeout

    constructor(private hub: Hub) {
        this.instanceId = randomUUID()
        this.pubSub = new PubSub(hub, {
            'hog-watcher-observations': (message) => {
                const { instanceId, observations }: EmittedHogWatcherObservations = JSON.parse(message)

                if (instanceId === this.instanceId) {
                    return
                }

                observations.forEach(({ id, observation }) => {
                    const observationsForId = (this.observations[id] = this.observations[id] ?? [])
                    this.observations[id] = mergeObservations([...observationsForId, observation])
                })
            },

            'hog-watcher-states': (message) => {
                // NOTE: This is only emitted by the leader so we can immediately add it to the list of states
                const { instanceId, states }: EmittedHogWatcherStates = JSON.parse(message)

                if (instanceId === this.instanceId) {
                    return
                }

                states.forEach(({ id, state }) => {
                    const statesForId = (this.states[id] = this.states[id] ?? [])
                    statesForId.push(state)
                })
            },
        })
    }

    async start() {
        await this.pubSub.start()

        if (process.env.NODE_ENV === 'test') {
            // Not setting up loop in test mode
            return
        }

        const loop = async () => {
            try {
                // Maybe add a slow function warning here
                await this.sync()
            } finally {
                this.interval = setTimeout(loop, OBSERVATION_PERIOD)
            }
        }

        await loop()
    }

    async stop() {
        await this.pubSub.stop()

        if (this.interval) {
            clearTimeout(this.interval)
        }
        if (!this.isLeader) {
            return
        }

        await runRedis(this.hub.redisPool, 'stop', async (client) => {
            return client.del(`${BASE_REDIS_KEY}/leader`)
        })

        await this.flushActiveObservations()
    }

    public getFunctionState(id: HogFunctionType['id']): HogWatcherState {
        return this.states[id]?.slice(-1)[0]?.state ?? HogWatcherState.healthy
    }

    private async checkIsLeader() {
        const leaderId = await runRedis(this.hub.redisPool, 'getLeader', async (client) => {
            // Set the leader to this instance if it is not set and add an expiry to it of twice our observation period
            const pipeline = client.pipeline()

            // TODO: This can definitely be done in a single command - just need to make sure the ttl is always extended if the ID is the same

            // @ts-expect-error - IORedis types don't allow for NX and EX in the same command
            pipeline.set(`${BASE_REDIS_KEY}/leader`, this.instanceId, 'NX', 'EX', (OBSERVATION_PERIOD * 3) / 1000)
            pipeline.get(`${BASE_REDIS_KEY}/leader`)
            const [_, res] = await pipeline.exec()

            // NOTE: IORedis types don't allow for NX and GET in the same command so we have to cast it to any
            return res[1] as string
        })

        this.isLeader = leaderId === this.instanceId

        if (this.isLeader) {
            status.info('👀', '[HogWatcher] I am the leader')
        }
    }

    public async sync() {
        // TODO: Implement this
        // 1. Expire all old observations and states
        // 2. Flush any active observations that we need to do redis (and pubsub)

        await this.checkIsLeader()
        await this.flushActiveObservations()

        if (this.isLeader) {
            await this.flushStates()
        }
    }

    private async flushActiveObservations() {
        const changes: EmittedHogWatcherObservations = {
            instanceId: this.instanceId,
            observations: [],
        }

        const period = periodTimestamp()

        Object.entries(this.currentObservations.observations).forEach(([id, observation]) => {
            if (observation.timestamp !== period) {
                changes.observations.push({ id, observation })
                this.observations[id] = this.observations[id] ?? []
                this.observations[id].push(observation)
                delete this.currentObservations.observations[id]
            }
        })

        if (!changes.observations.length) {
            return
        }

        // Write all the info to redis
        await runRedis(this.hub.redisPool, 'syncWithRedis', async (client) => {
            const pipeline = client.pipeline()

            changes.observations.forEach(({ id, observation }) => {
                // We key the observations by observerId and timestamp with a ttl of the max period we want to keep the data for
                const subKey = `${this.instanceId}/${observation.timestamp}`
                pipeline.hset(redisKeyObservations(id), subKey, JSON.stringify(observation))
                pipeline.expire(redisKeyObservations(id), (EVALUATION_PERIOD / 1000) * 2) // Expire at twice the evaluation period
            })

            return pipeline.exec()
        })

        // Now we can emit to the others so they can update their state
        await this.pubSub.publish('hog-watcher-observations', JSON.stringify(changes))
    }

    private async flushStates() {
        // Flushing states involves a couple of things and is only done by the leader to avoid clashes

        // 1. Prune old states that are no longer relevant (we only keep the last N states)
        // 2. Calculate the state for each function based on their existing observations and previous states
        // 3. If the state has changed, write it to redis and emit it to the others

        if (!this.isLeader) {
            status.warn('👀', '[HogWatcher] Only the leader can flush states')
            return
        }

        const changes: EmittedHogWatcherStates = {
            instanceId: this.instanceId,
            states: [],
        }

        Object.entries(this.observations).forEach(([id, observations]) => {
            const states = this.states[id] ?? []
            const currentState = states[states.length - 1]?.state ?? HogWatcherState.healthy
            const newState = deriveCurrentState(observations, states)

            if (currentState !== newState) {
                const state: HogWatcherStatePeriod = {
                    timestamp: periodTimestamp(),
                    state: newState,
                }

                this.states[id] = this.states[id] ?? []
                this.states[id].push(state)
                changes.states.push({ id, state })
            }
        })

        if (!changes.states.length) {
            return
        }

        status.info('👀', '[HogWatcher] Functions changed state', {
            changes: changes,
        })

        // Write all the info to redis
        await runRedis(this.hub.redisPool, 'syncWithRedis', async (client) => {
            const pipeline = client.pipeline()

            changes.states.forEach(({ id, state }) => {
                // We key the value with the timestamp as we want to keep a history of the states
                pipeline.zadd(redisKeyStates(id), state.timestamp, `${state.state}:${state.timestamp}`)
                // Limit to only MAX_RECORDED_STATES
                pipeline.zremrangebyrank(redisKeyStates(id), 0, -MAX_RECORDED_STATES)
            })

            return pipeline.exec()
        })

        // Now we can emit to the others so they can update their state
        await this.pubSub.publish('hog-watcher-states', JSON.stringify(changes))
    }

    async fetchWatcherIfNeeded(id: HogFunctionType['id']): Promise<HogWatcherSummary> {
        if (!this.summaries[id]) {
            this.summaries[id] = await this.fetchWatcher(id)
        }

        return this.summaries[id]
    }

    async fetchWatcher(id: HogFunctionType['id']): Promise<HogWatcherSummary> {
        const [states, observations] = await runRedis(this.hub.redisPool, 'fetchWatcher', async (client) => {
            const pipeline = client.pipeline()

            pipeline.zrange(redisKeyStates(id), 0, -1, 'WITHSCORES')
            pipeline.hgetall(redisKeyObservations(id))
            return pipeline.exec()
        })

        const statesParsed = states[1] as string[]
        const observationsParsed = observations[1] as Record<string, string>

        const statesArray: HogWatcherStatePeriod[] = []

        for (let i = 0; i < statesParsed.length; i += 2) {
            statesArray.push({
                timestamp: parseInt(statesParsed[i + 1]),
                state: parseInt(statesParsed[i].split(':')[0]) as HogWatcherState,
            })
        }

        const observationsArray = mergeObservations(Object.values(observationsParsed).map((x) => JSON.parse(x)))

        return {
            state: statesArray[statesArray.length - 1]?.state ?? HogWatcherState.healthy,
            rating: getAverageRating(observationsArray),
            states: statesArray,
            observations: observationsArray,
        }
    }
}
