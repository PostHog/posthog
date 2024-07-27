import { randomUUID } from 'node:crypto'
import { Counter } from 'prom-client'

import { CdpConfig, Hub } from '../../types'
import { PubSub } from '../../utils/pubsub'
import { status } from '../../utils/status'
import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult, HogFunctionType } from '../types'
import {
    EmittedHogWatcherObservations,
    EmittedHogWatcherStates,
    HogWatcherGlobalState,
    HogWatcherObservationPeriod,
    HogWatcherObservationPeriodWithInstanceId,
    HogWatcherRatingPeriod,
    HogWatcherState,
    HogWatcherStatePeriod,
    HogWatcherSummary,
} from './types'
import {
    BASE_REDIS_KEY,
    calculateRating,
    deriveCurrentStateFromRatings,
    last,
    periodTimestamp,
    runRedis,
    stripFalsey,
} from './utils'

const REDIS_KEY_STATE = `${BASE_REDIS_KEY}/state`

const hogStateChangeCounter = new Counter({
    name: 'cdp_hog_watcher_state_change',
    help: 'An function was moved to a different state',
    labelNames: ['state'],
})

export class HogWatcherActiveObservations {
    observations: Record<HogFunctionType['id'], HogWatcherObservationPeriod> = {}

    constructor(private config: CdpConfig) {}

    private addObservations(
        id: HogFunctionType['id'],
        incrs: Pick<
            Partial<HogWatcherObservationPeriod>,
            'successes' | 'failures' | 'asyncFunctionFailures' | 'asyncFunctionSuccesses'
        >
    ): void {
        if (!this.observations[id]) {
            this.observations[id] = {
                timestamp: periodTimestamp(this.config),
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
            this.addObservations(result.invocation.hogFunctionId, {
                successes: result.finished ? 1 : 0,
                failures: result.error ? 1 : 0,
            })
        )
    }

    observeAsyncFunctionResponses(responses: HogFunctionInvocationAsyncResponse[]) {
        // NOTE: This probably wants to be done using the response status instead :thinking:
        responses.forEach((response) =>
            this.addObservations(response.hogFunctionId, {
                asyncFunctionSuccesses: response.asyncFunctionResponse.error ? 0 : 1,
                asyncFunctionFailures: response.asyncFunctionResponse.error ? 1 : 0,
            })
        )
    }
}

export class HogWatcher {
    public readonly currentObservations: HogWatcherActiveObservations
    public states: Record<HogFunctionType['id'], HogWatcherState> = {}
    private queuedManualStates: Record<HogFunctionType['id'], HogWatcherState> = {}

    // Only set if we are the leader
    public globalState?: HogWatcherGlobalState
    // Only the leader should be able to write to the states
    public isLeader: boolean = false
    private pubSub: PubSub
    private instanceId: string
    private syncTimer?: NodeJS.Timeout

    constructor(private hub: Hub) {
        this.currentObservations = new HogWatcherActiveObservations(hub)

        this.instanceId = randomUUID()
        this.pubSub = new PubSub(hub, {
            'hog-watcher-states': (message) => {
                const { states }: EmittedHogWatcherStates = JSON.parse(message)

                this.states = {
                    ...this.states,
                    ...states,
                }
            },

            'hog-watcher-observations': (message) => {
                // We only care about observations from other instances if we have a global state already loaded
                if (!this.globalState) {
                    return
                }

                const { instanceId, observations }: EmittedHogWatcherObservations = JSON.parse(message)

                observations.forEach(({ id, observation }) => {
                    const items = (this.globalState!.observations[id] = this.globalState!.observations[id] ?? [])
                    items.push({
                        ...observation,
                        instanceId: instanceId,
                    })
                })
            },

            'hog-watcher-user-state-change': (message) => {
                if (!this.isLeader) {
                    return
                }

                const { states }: EmittedHogWatcherStates = JSON.parse(message)

                Object.entries(states).forEach(([id, state]) => {
                    this.queuedManualStates[id] = state
                })

                void this.syncLoop()
            },
        })
    }

    async start() {
        await this.pubSub.start()

        // Get the initial state of the watcher
        await this.syncStates()

        if (process.env.NODE_ENV === 'test') {
            // Not setting up loop in test mode
            return
        }

        await this.syncLoop()
    }

    async stop() {
        await this.pubSub.stop()

        if (this.syncTimer) {
            clearTimeout(this.syncTimer)
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
        return this.states[id] ?? HogWatcherState.healthy
    }

    private async checkIsLeader() {
        const leaderId = await runRedis(this.hub.redisPool, 'getLeader', async (client) => {
            // Set the leader to this instance if it is not set and add an expiry to it of twice our observation period
            const pipeline = client.pipeline()

            // TODO: This can definitely be done in a single command - just need to make sure the ttl is always extended if the ID is the same

            pipeline.set(
                `${BASE_REDIS_KEY}/leader`,
                this.instanceId,
                'NX',
                // @ts-expect-error - IORedis types don't allow for NX and EX in the same command
                'EX',
                (this.hub.CDP_WATCHER_OBSERVATION_PERIOD * 3) / 1000
            )
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

    public syncLoop = async () => {
        clearTimeout(this.syncTimer)
        try {
            await this.sync()
        } finally {
            this.syncTimer = setTimeout(() => this.syncLoop(), this.hub.CDP_WATCHER_OBSERVATION_PERIOD)
        }
    }

    public async sync() {
        await this.checkIsLeader()
        await this.flushActiveObservations()

        if (this.isLeader) {
            await this.syncState()
        } else {
            // Clear any states that are only relevant to the leader
            this.globalState = undefined
            this.queuedManualStates = {}
        }
    }

    private async flushActiveObservations() {
        const changes: EmittedHogWatcherObservations = {
            instanceId: this.instanceId,
            observations: [],
        }

        const period = periodTimestamp(this.hub)

        Object.entries(this.currentObservations.observations).forEach(([id, observation]) => {
            if (observation.timestamp !== period) {
                changes.observations.push({ id, observation })
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
                const subKey = `observation:${id}:${this.instanceId}:${observation.timestamp}`
                pipeline.hset(REDIS_KEY_STATE, subKey, Serializer.serializeObservation(observation))
            })

            return pipeline.exec()
        })

        // Now we can emit to the others so they can update their state
        await this.pubSub.publish('hog-watcher-observations', JSON.stringify(changes))
    }

    private async syncState() {
        // Flushing states involves a couple of things and is only done by the leader to avoid clashes

        // 1. Prune old states that are no longer relevant (we only keep the last N states)
        // 2. Calculate the state for each function based on their existing observations and previous states
        // 3. If the state has changed, write it to redis and emit it to the others

        if (!this.isLeader) {
            status.warn('👀', '[HogWatcher] Only the leader can flush states')
            return
        }

        const globalState = (this.globalState = this.globalState ?? (await this.fetchState()))

        const stateChanges: EmittedHogWatcherStates = {
            instanceId: this.instanceId,
            states: {},
        }

        // We want to gather all observations that are at least 1 period older than the current period
        // That gives enough time for each worker to have pushed out their observations

        const period = periodTimestamp(this.hub)
        const keysToRemove: string[] = []
        const changedHogFunctionRatings = new Set<HogFunctionType['id']>()
        const RATINGS_PERIOD_MASK = this.hub.CDP_WATCHER_OBSERVATION_PERIOD * 2

        // Group the observations by functionId and timestamp and generate their rating
        Object.entries(globalState.observations).forEach(([id, observations]) => {
            const groupedByTimestamp: Record<string, HogWatcherObservationPeriodWithInstanceId> = {}
            const [oldEnoughObservations, others] = observations.reduce(
                (acc, observation) => {
                    if (observation.timestamp <= period - RATINGS_PERIOD_MASK) {
                        // Add the key to be removed from redis later
                        keysToRemove.push(`observation:${id}:${observation.instanceId}:${observation.timestamp}`)
                        acc[0].push(observation)
                    } else {
                        acc[1].push(observation)
                    }
                    return acc
                },
                [[], []] as [HogWatcherObservationPeriodWithInstanceId[], HogWatcherObservationPeriodWithInstanceId[]]
            )

            // Keep only the observations that aren't ready to be persisted
            if (others.length) {
                globalState.observations[id] = others
            } else {
                delete globalState.observations[id]
            }

            // Group them all by timestamp to generate a new rating
            oldEnoughObservations.forEach((observation) => {
                const key = `${id}:${observation.timestamp}`
                groupedByTimestamp[key] = groupedByTimestamp[key] ?? {
                    timestamp: observation.timestamp,
                    successes: 0,
                    failures: 0,
                    asyncFunctionSuccesses: 0,
                    asyncFunctionFailures: 0,
                }
                groupedByTimestamp[key].successes += observation.successes
                groupedByTimestamp[key].failures += observation.failures
                groupedByTimestamp[key].asyncFunctionSuccesses += observation.asyncFunctionSuccesses
                groupedByTimestamp[key].asyncFunctionFailures += observation.asyncFunctionFailures
            })

            Object.entries(groupedByTimestamp).forEach(([_, observation]) => {
                const rating = calculateRating(observation)
                globalState.ratings[id] = globalState.ratings[id] ?? []
                globalState.ratings[id].push({ timestamp: observation.timestamp, rating: rating })
                globalState.ratings[id] = globalState.ratings[id].slice(-this.hub.CDP_WATCHER_MAX_RECORDED_RATINGS)

                changedHogFunctionRatings.add(id)
            })
        })

        const transitionToState = (id: HogFunctionType['id'], newState: HogWatcherState) => {
            const state: HogWatcherStatePeriod = {
                timestamp: periodTimestamp(this.hub),
                state: newState,
            }

            globalState.states[id] = globalState.states[id] ?? []
            globalState.states[id].push(state)
            globalState.states[id] = globalState.states[id].slice(-this.hub.CDP_WATCHER_MAX_RECORDED_STATES)
            stateChanges.states[id] = newState
            hogStateChangeCounter.inc({ state: newState })
        }

        changedHogFunctionRatings.forEach((id) => {
            // Build the new ratings to be written
            // Check if the state has changed and if so add it to the list of changes
            const newRatings = globalState.ratings[id]
            const currentState = last(globalState.states[id])?.state ?? HogWatcherState.healthy
            const newState = deriveCurrentStateFromRatings(this.hub, newRatings, globalState.states[id] ?? [])

            if (currentState !== newState) {
                transitionToState(id, newState)
            }
        })

        // In addition we need to check temporarily disabled functions and move them back to overflow if they are behaving well
        Object.entries(globalState.states).forEach(([id, states]) => {
            const currentState = last(states)?.state
            if (currentState === HogWatcherState.disabledForPeriod) {
                // Also check the state change here
                const newState = deriveCurrentStateFromRatings(this.hub, globalState.ratings[id] ?? [], states)

                if (newState !== currentState) {
                    transitionToState(id, newState)
                }
            }
        })

        // Finally we make sure any manual changes that came in are applied
        Object.entries(this.queuedManualStates).forEach(([id, state]) => {
            transitionToState(id, state)
            delete this.queuedManualStates[id]
        })

        if (!changedHogFunctionRatings.size && !Object.keys(stateChanges.states).length) {
            // Nothing to do
            return
        }

        status.info('👀', '[HogWatcher] Functions changed state', {
            changes: stateChanges,
        })

        // Finally write the state summary
        const states: Record<HogFunctionType['id'], HogWatcherState> = Object.fromEntries(
            Object.entries(globalState.states).map(([id, states]) => [id, last(states)!.state])
        )

        // Finally we write the changes to redis and emit them to the others
        await runRedis(this.hub.redisPool, 'syncWithRedis', async (client) => {
            const pipeline = client.pipeline()

            // Remove old observations
            keysToRemove.forEach((key) => {
                pipeline.hdel(REDIS_KEY_STATE, key)
            })

            // Write the new ratings
            changedHogFunctionRatings.forEach((id) => {
                const ratings = globalState.ratings[id] ?? []
                pipeline.hset(REDIS_KEY_STATE, `ratings:${id}`, Serializer.serializeRatings(ratings))
            })

            Object.keys(stateChanges.states).forEach((id) => {
                const states = globalState.states[id] ?? []
                pipeline.hset(REDIS_KEY_STATE, `states:${id}`, Serializer.serializeStates(states))
            })

            // Write the new states
            pipeline.hset(REDIS_KEY_STATE, 'states', Serializer.serializeAllStates(states))

            return pipeline.exec()
        })

        // // Now we can emit to the others so they can update their state
        await this.pubSub.publish('hog-watcher-states', JSON.stringify(stateChanges))
    }

    async syncStates(): Promise<Record<HogFunctionType['id'], HogWatcherState>> {
        const res = await runRedis(this.hub.redisPool, 'fetchWatcher', async (client) => {
            return client.hget(REDIS_KEY_STATE, 'states')
        })

        this.states = res ? Serializer.deserializeAllStates(res) : {}

        return this.states
    }

    /**
     * Fetch the summary for HogFunction (used by the UI, hence no caching)
     */
    async fetchWatcher(id: HogFunctionType['id']): Promise<HogWatcherSummary> {
        const [statesStr, ratingsStr] = await runRedis(this.hub.redisPool, 'fetchWatcher', async (client) => {
            return client.hmget(REDIS_KEY_STATE, `states:${id}`, `ratings:${id}`)
        })

        const states: HogWatcherStatePeriod[] = statesStr ? Serializer.deserializeStates(statesStr) : []
        const ratings: HogWatcherRatingPeriod[] = ratingsStr ? Serializer.deserializeRatings(ratingsStr) : []

        return {
            state: last(states)?.state ?? HogWatcherState.healthy,
            states: states,
            ratings: ratings,
        }
    }

    async forceStateChange(id: HogFunctionType['id'], state: HogWatcherState): Promise<void> {
        // Ensure someone is the leader
        await this.checkIsLeader()
        const changes: EmittedHogWatcherStates = {
            instanceId: this.instanceId,
            states: {
                [id]: state,
            },
        }

        await this.pubSub.publish('hog-watcher-user-state-change', JSON.stringify(changes))
    }

    /**
     * Fetch the entire state object parsing into a usable object
     */
    async fetchState(): Promise<HogWatcherGlobalState> {
        const redisState = await runRedis(this.hub.redisPool, 'fetchWatcher', async (client) => {
            return client.hgetall(REDIS_KEY_STATE)
        })

        return Serializer.deserializeGlobalState(redisState)
    }
}

class Serializer {
    // Serializer to help parsing back and forth to redis - mostly focused on reducing the size of the stored values

    static deserializeGlobalState(redisState: Record<string, string>): HogWatcherGlobalState {
        const response: HogWatcherGlobalState = {
            states: {},
            ratings: {},
            observations: {},
        }

        Object.entries(redisState).forEach(([key, value]) => {
            const [kind, id, ...rest] = key.split(':')
            if (kind === 'states' && id) {
                response.states[id] = this.deserializeStates(value)
            } else if (kind === 'ratings') {
                response.ratings[id] = this.deserializeRatings(value)
            } else if (kind === 'observation') {
                const [instanceId, timestamp] = rest
                const partial = this.deserializeObservation(value)
                const observations: HogWatcherObservationPeriodWithInstanceId[] = (response.observations[id] =
                    response.observations[id] ?? [])

                observations.push({
                    ...partial,
                    instanceId: instanceId,
                    timestamp: parseInt(timestamp),
                })
            } else if (kind === 'states') {
                // We can ignore this as it is the global state
            } else {
                status.warn('👀', `Unknown key kind ${kind} in fetchState`)
            }
        })

        return response
    }

    static serializeAllStates(val: Record<HogFunctionType['id'], HogWatcherState>): string {
        const obj = Object.entries(val).map(([id, state]) => [id, state])
        return JSON.stringify(obj)
    }

    static deserializeAllStates(val: string): Record<HogFunctionType['id'], HogWatcherState> {
        const obj: (string | HogWatcherState)[][] = JSON.parse(val)
        return Object.fromEntries(obj)
    }

    static serializeStates(val: HogWatcherStatePeriod[]): string {
        const obj = val.map((x) => ({ t: x.timestamp, s: x.state }))
        return JSON.stringify(obj)
    }

    static deserializeStates(val: string): HogWatcherStatePeriod[] {
        const obj = JSON.parse(val)
        return obj.map((x: { t: number; s: HogWatcherState }) => ({ timestamp: x.t, state: x.s }))
    }

    static serializeRatings(val: HogWatcherRatingPeriod[]): string {
        const obj = val.map((x) => ({ t: x.timestamp, r: x.rating }))
        return JSON.stringify(obj)
    }

    static deserializeRatings(val: string): HogWatcherRatingPeriod[] {
        const obj = JSON.parse(val)
        return obj.map((x: { t: number; r: number }) => ({ timestamp: x.t, rating: x.r }))
    }

    static serializeObservation(val: HogWatcherObservationPeriod): string {
        const obj = stripFalsey({
            t: val.timestamp,
            s: val.successes,
            f: val.failures,
            af: val.asyncFunctionFailures,
            as: val.asyncFunctionSuccesses,
        })
        return JSON.stringify(obj)
    }

    static deserializeObservation(val: string): HogWatcherObservationPeriod {
        const obj = JSON.parse(val)
        return {
            timestamp: obj.t,
            successes: obj.s ?? 0,
            failures: obj.f ?? 0,
            asyncFunctionFailures: obj.af ?? 0,
            asyncFunctionSuccesses: obj.as ?? 0,
        }
    }
}
