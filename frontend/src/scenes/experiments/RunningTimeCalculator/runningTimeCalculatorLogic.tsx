import { actions, kea, path, reducers, selectors } from 'kea'

import type { runningTimeCalculatorLogicType } from './runningTimeCalculatorLogicType'

export const TIMEFRAME_HISTORICAL_DATA_DAYS = 14
export const VARIANCE_SCALING_FACTOR = 2

export const runningTimeCalculatorLogic = kea<runningTimeCalculatorLogicType>([
    path(['scenes', 'experiments', 'RunningTimeCalculator', 'runningTimeCalculatorLogic']),
    actions({
        setMinimumDetectableEffect: (value: number) => ({ value }),
    }),
    reducers({
        eventOrAction: ['click' as string, { setEventOrAction: (_, { value }) => value }],
        minimumDetectableEffect: [
            5 as number,
            {
                setMinimumDetectableEffect: (_, { value }) => value,
            },
        ],
        // To be loaded from a query
        uniqueUsers: [
            28000 as number,
            {
                setUniqueUsers: (_, { value }) => value,
            },
        ],
        // To be loaded from a query
        averageEventsPerUser: [
            4 as number,
            {
                setAverageEventsPerUser: (_, { value }) => value,
            },
        ],
    }),
    selectors({
        variance: [
            (s) => [s.averageEventsPerUser],
            (averageEventsPerUser: number) => {
                return averageEventsPerUser * VARIANCE_SCALING_FACTOR
            },
        ],
        recommendedSampleSize: [
            (s) => [s.minimumDetectableEffect, s.variance],
            (minimumDetectableEffect: number, variance: number): number => {
                const numberOfVariants = 2
                const standardDeviation = Math.sqrt(variance)

                return ((16 * variance) / ((minimumDetectableEffect / 100) * standardDeviation) ** 2) * numberOfVariants
            },
        ],
        recommendedRunningTime: [
            (s) => [s.recommendedSampleSize, s.uniqueUsers],
            (recommendedSampleSize: number, uniqueUsers: number): number => {
                return recommendedSampleSize / (uniqueUsers / TIMEFRAME_HISTORICAL_DATA_DAYS)
            },
        ],
    }),
])
