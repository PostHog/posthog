import { HogFunctionType } from '../types'

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

export type HogWatcherRatingPeriod = {
    timestamp: number
    rating: number
}

export type HogWatcherObservationPeriod = {
    timestamp: number
    successes: number
    failures: number
    asyncFunctionFailures: number
    asyncFunctionSuccesses: number
}

export type HogWatcherObservationPeriodWithInstanceId = HogWatcherObservationPeriod & {
    instanceId: string
}

export type HogWatcherSummary = {
    state: HogWatcherState
    states: HogWatcherStatePeriod[]
    ratings: HogWatcherRatingPeriod[]
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
        [key: HogFunctionType['id']]: HogWatcherState
    }
}

// Deserialized version of what is stored in redis
export type HogWatcherGlobalState = {
    /** Summary of all state history for every function */
    states: Record<HogFunctionType['id'], HogWatcherStatePeriod[]>
    /** Summary of all rating history for all functions */
    ratings: Record<HogFunctionType['id'], HogWatcherRatingPeriod[]>
    /** All in progress observations that have not been serialized into ratings */
    observations: Record<HogFunctionType['id'], HogWatcherObservationPeriodWithInstanceId[]>
}
