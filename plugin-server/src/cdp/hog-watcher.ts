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

export type HogWatcherObservationPeriod = {
    timestamp: number
    rating: number
    successes: number
    failures: number
    asyncFunctionFailures: number
    asyncFunctionSuccesses: number
}

export type HogWatcherStatePeriod = {
    timestamp: number
    state: HogWatcherState
}

export const OBSERVATION_PERIOD = 10000 // Adjust this for more or less granular checking
export const EVALUATION_PERIOD = OBSERVATION_PERIOD * 100 // Essentially how many periods to keep in memory
export const DISABLED_PERIOD = 1000 * 60 * 10 // 10 minutes
export const MAX_RECORDED_STATES = 10
export const MAX_ALLOWED_TEMPORARY_DISABLES = MAX_RECORDED_STATES / 2
export const MIN_OBSERVATIONS = 3

export const OVERFLOW_THRESHOLD = 0.8
export const DISABLE_THRESHOLD = 0.5

export class HogWatcherObserver {
    observations: HogWatcherObservationPeriod[] = []
    states: HogWatcherStatePeriod[] = []

    constructor(private id: HogFunctionType['id']) {}

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
            Partial<HogWatcherObservationPeriod>,
            'successes' | 'failures' | 'asyncFunctionFailures' | 'asyncFunctionSuccesses'
        >
    ): HogWatcherObservationPeriod {
        const observation = this.getObservation()

        observation.successes += incrs.successes ?? 0
        observation.failures += incrs.failures ?? 0
        observation.asyncFunctionFailures += incrs.asyncFunctionFailures ?? 0
        observation.asyncFunctionSuccesses += incrs.asyncFunctionSuccesses ?? 0

        observation.rating = this.calculateRating(observation)
        return observation
    }

    private periodTimestamp(): number {
        // Returns the timestamp but rounded to the nearest period (e.g. 1 minute)
        return Math.floor(Date.now() / OBSERVATION_PERIOD) * OBSERVATION_PERIOD
    }

    private getObservation(): HogWatcherObservationPeriod {
        let lastObservation = this.observations[this.observations.length - 1]

        if (!lastObservation || lastObservation.timestamp !== this.periodTimestamp()) {
            lastObservation = {
                timestamp: this.periodTimestamp(),
                rating: 0,
                successes: 0,
                failures: 0,
                asyncFunctionFailures: 0,
                asyncFunctionSuccesses: 0,
            }

            this.observations.push(lastObservation)
        }

        return lastObservation
    }

    private calculateRating(observation: HogWatcherObservationPeriod): number {
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
    observations: Record<HogFunctionType['id'], HogWatcherObserver> = {}

    constructor() {}

    observeResults(results: HogFunctionInvocationResult[]) {
        // TODO: Actually measure something and store the result
        results.forEach((result) => {
            this.getObserver(result.id).addObservations({
                successes: result.finished ? 1 : 0,
                failures: result.error ? 1 : 0,
            })
        })
    }

    observeAsyncFunctionResponses(responses: HogFunctionInvocationAsyncResponse[]) {
        // NOTE: This probably wants to be done using the response status instead :thinking:
        responses.forEach((response) => {
            this.getObserver(response.hogFunctionId).addObservations({
                asyncFunctionSuccesses: response.error ? 0 : 1,
                asyncFunctionFailures: response.error ? 1 : 0,
            })
        })
    }

    isHogFunctionOverflowed(hogFunctionId: HogFunctionType['id']): boolean {
        return this.getObserver(hogFunctionId).currentState() === HogWatcherState.overflowed
    }

    isHogFunctionDisabled(hogFunctionId: HogFunctionType['id']): boolean {
        return this.getObserver(hogFunctionId).currentState() >= HogWatcherState.disabledForPeriod
    }

    private getObserver(id: HogFunctionType['id']): HogWatcherObserver {
        if (!this.observations[id]) {
            this.observations[id] = new HogWatcherObserver(id)
        }

        return this.observations[id]
    }
}
