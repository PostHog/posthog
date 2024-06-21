import { Redis } from 'ioredis'

import { Hub, PluginsServerConfig, RedisPool } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult, HogFunctionType } from './types'
import { randomUUID } from 'node:crypto'
import { PubSub } from '../utils/pubsub'

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
    rating: number
}

export type HogWatcherObservationPeriodDetailed = HogWatcherObservationPeriod & {
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

export type PersistedHogWatcherObservations = {
    [key: string]: HogWatcherObservationPeriodDetailed
}

export type EmittedHogWatcherObservation = {
    id: HogFunctionType['id']
    observerId: string
    observation: HogWatcherObservationPeriodDetailed
}

/*
This all gets serialized to redis in a way that we can have shared state between multiple instances of the plugin server

# Timestamps are rounded to a period so we can easily group them

ZSET @posthog/hog-watcher/observations/<id>/successes
# Whenever we pass the threshold for a evaluation period, we increment that period in the ZSET with our successes and failures


FIELD @posthog/hog-watcher/observations/<id> = {
  [uuid]: HogWatcherObservationPeriodDetailed
}

We set a ttl on the key to the max period we want to keep the data for. This way each pod can fetch all observations and states.

*/

const REDIS_TIMEOUT_SECONDS = 5

export const OBSERVATION_PERIOD = 10000 // Adjust this for more or less granular checking
export const EVALUATION_PERIOD = OBSERVATION_PERIOD * 100 // Essentially how many periods to keep in memory
export const DISABLED_PERIOD = 1000 * 60 * 10 // 10 minutes
export const MAX_RECORDED_STATES = 10
export const MAX_ALLOWED_TEMPORARY_DISABLES = MAX_RECORDED_STATES / 2
export const MIN_OBSERVATIONS = 3

export const OVERFLOW_THRESHOLD = 0.8
export const DISABLE_THRESHOLD = 0.5

export class HogWatcherObserver {
    observations: HogWatcherObservationPeriodDetailed[] = []
    states: HogWatcherStatePeriod[] = []
    observerId: string

    // The current observation period
    observation?: HogWatcherObservationPeriodDetailed

    constructor(public hogFunctionId: HogFunctionType['id']) {
        this.observerId = randomUUID()
    }

    public getSummary(): HogWatcherSummary {
        return {
            state: this.currentState(),
            rating: this.averageRating(),
            states: this.states,
            observations: this.observations.map((x) => ({
                timestamp: x.timestamp,
                rating: x.rating,
            })),
        }
    }

    public currentState(): HogWatcherState {
        // TODO: Prune old observations and states
        // Observations are pruned by age
        this.observations = this.observations.filter((x) => Date.now() - x.timestamp < EVALUATION_PERIOD)

        // States are pruned by a max length rather than time
        if (this.states.length > MAX_RECORDED_STATES) {
            this.states = this.states.slice(this.states.length - MAX_RECORDED_STATES)
        }

        const currentState = this.states[this.states.length - 1] ?? {
            timestamp: Date.now(),
            state: HogWatcherState.healthy,
        }

        const averageRating = this.averageRating()

        if (currentState.state === HogWatcherState.disabledIndefinitely) {
            return HogWatcherState.disabledIndefinitely
        }

        // If we are disabled for a period then we only check if it should no longer be disabled
        if (currentState.state === HogWatcherState.disabledForPeriod) {
            if (Date.now() - currentState.timestamp > DISABLED_PERIOD) {
                return this.moveToState(HogWatcherState.overflowed)
            }
        }

        if (this.observations.length < MIN_OBSERVATIONS) {
            // We need to give the function a chance to run before we can evaluate it
            return currentState.state
        }

        if (currentState.state === HogWatcherState.overflowed) {
            if (averageRating > OVERFLOW_THRESHOLD) {
                // The function is behaving well again - move it to healthy
                return this.moveToState(HogWatcherState.healthy)
            }

            if (averageRating < DISABLE_THRESHOLD) {
                // The function is behaving worse than overflow can accept - disable it
                const disabledStates = this.states.filter((x) => x.state === HogWatcherState.disabledForPeriod)

                if (disabledStates.length >= MAX_ALLOWED_TEMPORARY_DISABLES) {
                    // this function has spent half of the time in temporary disabled so we disable it indefinitely
                    return this.moveToState(HogWatcherState.disabledIndefinitely)
                }

                return this.moveToState(HogWatcherState.disabledForPeriod)
            }
        }

        if (currentState.state === HogWatcherState.healthy) {
            if (averageRating < OVERFLOW_THRESHOLD) {
                return this.moveToState(HogWatcherState.overflowed)
            }
        }

        return currentState.state
    }

    private moveToState(state: HogWatcherState): HogWatcherState {
        this.states.push({
            timestamp: Date.now(),
            state,
        })

        // TODO: Somehow report this back to PostHog so we can display it in the UI

        return state
    }

    public addObservations(
        incrs: Pick<
            Partial<HogWatcherObservationPeriodDetailed>,
            'successes' | 'failures' | 'asyncFunctionFailures' | 'asyncFunctionSuccesses'
        >
    ): HogWatcherObservationPeriodDetailed {
        const observation = this.getOrCreateCurrentObservation()

        observation.successes += incrs.successes ?? 0
        observation.failures += incrs.failures ?? 0
        observation.asyncFunctionFailures += incrs.asyncFunctionFailures ?? 0
        observation.asyncFunctionSuccesses += incrs.asyncFunctionSuccesses ?? 0

        observation.rating = this.calculateRating(observation)
        return observation
    }

    public receiveObservation(observation: HogWatcherObservationPeriodDetailed) {
        // TODO: We should probably merge the observations instead of just replacing them
        const existing = this.observations.find((x) => x.timestamp === observation.timestamp)
        if (existing) {
            existing.successes += observation.successes
            existing.failures += observation.failures
            existing.asyncFunctionFailures += observation.asyncFunctionFailures
            existing.asyncFunctionSuccesses += observation.asyncFunctionSuccesses
            existing.rating = this.calculateRating(existing)
        } else {
            this.observations.push(observation)
        }
    }

    private periodTimestamp(): number {
        // Returns the timestamp but rounded to the nearest period (e.g. 1 minute)
        return Math.floor(Date.now() / OBSERVATION_PERIOD) * OBSERVATION_PERIOD
    }

    private getOrCreateCurrentObservation(): HogWatcherObservationPeriodDetailed {
        if (!this.observation) {
            this.observation = {
                timestamp: this.periodTimestamp(),
                rating: 0,
                successes: 0,
                failures: 0,
                asyncFunctionFailures: 0,
                asyncFunctionSuccesses: 0,
            }
        }

        return this.observation
    }

    private calculateRating(observation: HogWatcherObservationPeriodDetailed): number {
        // Rating is from 0 to 1
        // 1 - Function is working perfectly
        // 0 - Function is not working at all

        const totalInvocations = observation.successes + observation.failures
        const totalAsyncInvocations = observation.asyncFunctionSuccesses + observation.asyncFunctionFailures

        const successRate = totalInvocations ? observation.successes / totalInvocations : 1
        const asyncSuccessRate = totalAsyncInvocations ? observation.asyncFunctionSuccesses / totalAsyncInvocations : 1

        return Math.min(1, successRate, asyncSuccessRate)
    }

    public averageRating(): number {
        return this.observations.reduce((acc, x) => acc + x.rating, 0) / this.observations.length
    }
}

/**
 * HogWatcher is responsible for observing metrics of running hog functions, including their async calls.
 * It build a rating for each function and decides whether that function is _hogging_ resources.
 * If so, it marks it as such and then can be used to control the flow of the function.
 */
export class HogWatcher {
    observers: Record<HogFunctionType['id'], HogWatcherObserver> = {}
    pubSub: PubSub
    interval?: NodeJS.Timeout

    constructor(private hub: Hub) {
        this.pubSub = new PubSub(hub, {
            'hog-watcher-observations': async (message) => {
                const observationsList: EmittedHogWatcherObservation[] = JSON.parse(message)

                observationsList.map(async ({ id, observerId, observation }) => {
                    const observer = this.observers[id]
                    if (observer && observer.observerId !== observerId) {
                        observer.receiveObservation(observation)
                    }
                })
            },
        })
    }

    async start() {
        await this.pubSub.start()

        this.interval = setInterval(() => this.syncObservations())
    }

    async observeResults(results: HogFunctionInvocationResult[]) {
        // TODO: Actually measure something and store the result
        await Promise.all(
            results.map(async (result) =>
                this.getObserver(result.hogFunctionId).then((x) =>
                    x.addObservations({
                        successes: result.finished ? 1 : 0,
                        failures: result.error ? 1 : 0,
                    })
                )
            )
        )
    }

    async observeAsyncFunctionResponses(responses: HogFunctionInvocationAsyncResponse[]) {
        // NOTE: This probably wants to be done using the response status instead :thinking:
        await Promise.all(
            responses.map(async (response) =>
                this.getObserver(response.hogFunctionId).then((x) =>
                    x.addObservations({
                        asyncFunctionSuccesses: response.error ? 0 : 1,
                        asyncFunctionFailures: response.error ? 1 : 0,
                    })
                )
            )
        )
    }

    async isHogFunctionOverflowed(hogFunctionId: HogFunctionType['id']): Promise<boolean> {
        return (await this.getObserver(hogFunctionId)).currentState() === HogWatcherState.overflowed
    }

    async isHogFunctionDisabled(hogFunctionId: HogFunctionType['id']): Promise<boolean> {
        return (await this.getObserver(hogFunctionId)).currentState() >= HogWatcherState.disabledForPeriod
    }

    public async getObserver(id: HogFunctionType['id']): Promise<HogWatcherObserver> {
        if (!this.observers[id]) {
            this.observers[id] = new HogWatcherObserver(id)
        }

        return await Promise.resolve(this.observers[id])
    }

    private async syncObservations() {
        /**
         * NOTE on Redis syncing
         *
         * We want to make sure that multiple consumers are kept up to date with each other with the least number of operations necessary.
         * We periodically (inline with the observation period) write the observations to redis so that we can retrieve the state of the functions.
         * We then need to get updates whenever they happen. We could do this by polling the redis instance for changes.
         *
         * Or we could use pubsub to notify all instances of changes, recording the change in memory, meaning we only need to read from redis on the initial startup.
         */

        const items: EmittedHogWatcherObservation[] = []

        Object.values(this.observers).forEach((observer) => {
            if (observer.observation) {
                items.push({
                    id: observer.hogFunctionId,
                    observerId: observer.observerId,
                    observation: observer.observation,
                })

                observer.observations.push(observer.observation)
                observer.observation = undefined
            }
        })

        // Write all the info to redis
        await this.run('syncWithRedis', async (client) => {
            const pipeline = client.pipeline()

            items.forEach(({ id, observerId, observation }) => {
                pipeline.hset(`@posthog/hog-watcher/observations/${id}`, observerId, JSON.stringify(observation))
            })

            return pipeline.exec()
        })

        if (!items.length) {
            return
        }

        await this.pubSub.publish('hog-watcher-observations', JSON.stringify(items))
    }

    private async run<T>(description: string, fn: (client: Redis) => Promise<T>): Promise<T> {
        const client = await this.hub.redisPool.acquire()
        const timeout = timeoutGuard(
            `${description} delayed. Waiting over ${REDIS_TIMEOUT_SECONDS} seconds.`,
            undefined,
            REDIS_TIMEOUT_SECONDS * 1000
        )
        try {
            return await fn(client)
        } finally {
            clearTimeout(timeout)
            await this.hub.redisPool.release(client)
        }
    }
}
