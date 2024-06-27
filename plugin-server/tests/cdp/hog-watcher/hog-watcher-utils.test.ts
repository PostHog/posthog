jest.mock('../../../src/utils/now', () => {
    return {
        now: jest.fn(() => Date.now()),
    }
})

import {
    HogWatcherObservationPeriod,
    HogWatcherRatingPeriod,
    HogWatcherState,
    HogWatcherStatePeriod,
} from '../../../src/cdp/hog-watcher/types'
import { calculateRating, deriveCurrentStateFromRatings, periodTimestamp } from '../../../src/cdp/hog-watcher/utils'
import { defaultConfig } from '../../../src/config/config'

const config = defaultConfig

describe('HogWatcher.utils', () => {
    describe('calculateRating', () => {
        // TODO: Change rating to account for numbers as well - low volume failures can still have a high rating as their impact is not so bad
        const cases: Array<[Partial<HogWatcherObservationPeriod>, number]> = [
            [{ successes: 9, failures: 1 }, 0.9],
            [{ successes: 1, failures: 1 }, 0.5],
            [{ successes: 0, failures: 1 }, 0],
            [{ successes: 1, failures: 0 }, 1],
            [{ asyncFunctionSuccesses: 9, asyncFunctionFailures: 1 }, 0.9],
            [{ asyncFunctionSuccesses: 1, asyncFunctionFailures: 1 }, 0.5],
            [{ asyncFunctionSuccesses: 0, asyncFunctionFailures: 1 }, 0],
            [{ asyncFunctionSuccesses: 1, asyncFunctionFailures: 0 }, 1],

            // Mixed results - currently whichever is worse is the rating
            [{ successes: 9, failures: 1, asyncFunctionSuccesses: 1, asyncFunctionFailures: 1 }, 0.5],
            [{ successes: 1, failures: 1, asyncFunctionSuccesses: 9, asyncFunctionFailures: 1 }, 0.5],
            [{ successes: 1, failures: 1, asyncFunctionSuccesses: 1, asyncFunctionFailures: 1 }, 0.5],
            [{ successes: 0, failures: 0, asyncFunctionSuccesses: 9, asyncFunctionFailures: 1 }, 0.9],
        ]

        it.each(cases)('should calculate the rating %s of %s', (vals, rating) => {
            const observation: HogWatcherObservationPeriod = {
                timestamp: Date.now(),
                successes: 0,
                failures: 0,
                asyncFunctionFailures: 0,
                asyncFunctionSuccesses: 0,
                ...vals,
            }
            expect(calculateRating(observation)).toBe(rating)
        })
    })

    describe('deriveCurrentStateFromRatings', () => {
        let now: number
        let ratings: HogWatcherRatingPeriod[]
        let states: HogWatcherStatePeriod[]

        beforeEach(() => {
            now = periodTimestamp(config)
            ratings = []
            states = []

            jest.useFakeTimers()
            jest.setSystemTime(now)
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        const advanceTime = (ms: number) => {
            jest.advanceTimersByTime(ms)
        }

        const updateState = (newRatings: number[], newStates: HogWatcherState[]) => {
            for (let i = 0; i < Math.max(newRatings.length, newStates.length); i++) {
                advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)

                if (newStates[i]) {
                    states.push({
                        timestamp: periodTimestamp(config),
                        state: newStates[i],
                    })
                }

                if (typeof newRatings[i] === 'number') {
                    ratings.push({
                        timestamp: Date.now(),
                        rating: newRatings[i],
                    })
                }
            }
        }

        const currentState = () => deriveCurrentStateFromRatings(config, ratings, states)
        const getAverageRating = () =>
            ratings.length ? ratings.reduce((acc, x) => acc + x.rating, 0) / ratings.length : 0

        describe('1 - healthy', () => {
            it('should be healthy with no ratings or previous states', () => {
                expect(currentState()).toBe(HogWatcherState.healthy)
            })

            it.each(Object.values(HogWatcherState))(
                'should be whatever the last state is (%s) if no ratings',
                (lastState) => {
                    updateState([], [lastState as any])
                    expect(currentState()).toBe(lastState)
                }
            )

            it('should not change if too few ratings', () => {
                updateState([0, 0], [])
                expect(getAverageRating()).toEqual(0)
                expect(currentState()).toBe(HogWatcherState.healthy)
            })

            it('should move to overflow if enough ratings are unhealthy', () => {
                updateState([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6], [])
                expect(states).toMatchObject([])
                expect(getAverageRating()).toBeLessThan(config.CDP_WATCHER_OVERFLOW_RATING_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })
        })

        describe('2 - overflow', () => {
            it('should stay in overflow if the rating does not change ', () => {
                updateState([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6], [])
                expect(currentState()).toBe(HogWatcherState.overflowed)
                expect(getAverageRating()).toBeLessThan(config.CDP_WATCHER_OVERFLOW_RATING_THRESHOLD)
                expect(getAverageRating()).toBeGreaterThan(config.CDP_WATCHER_DISABLED_RATING_THRESHOLD)

                updateState([0.5, 0.5, 0.6, 0.7, 0.8, 1, 0.8], [])
                expect(getAverageRating()).toBeLessThan(config.CDP_WATCHER_OVERFLOW_RATING_THRESHOLD)
                expect(getAverageRating()).toBeGreaterThan(config.CDP_WATCHER_DISABLED_RATING_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })

            it('should move back to healthy with enough healthy activity ', () => {
                updateState([], [HogWatcherState.overflowed])
                expect(currentState()).toBe(HogWatcherState.overflowed)
                updateState([0.5, 0.8, 0.9, 0.9, 1, 0.9, 1], [])
                expect(getAverageRating()).toBeGreaterThan(config.CDP_WATCHER_OVERFLOW_RATING_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.healthy)
            })

            it('should move to overflow if enough observations are unhealthy', () => {
                updateState([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6], [])
                expect(states).toMatchObject([])
                expect(getAverageRating()).toBeLessThan(config.CDP_WATCHER_OVERFLOW_RATING_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })

            it('should move to disabledForPeriod if sustained lower', () => {
                updateState([0.5, 0.4, 0.4], [])
                expect(currentState()).toBe(HogWatcherState.overflowed)
                updateState([], [HogWatcherState.overflowed]) // Add the new state
                expect(currentState()).toBe(HogWatcherState.overflowed) // Should still be the same
                updateState([0.5, 0.4], []) // Add nearly enough ratings for next evaluation
                expect(currentState()).toBe(HogWatcherState.overflowed) // Should still be the same
                updateState([0.4], []) // One more rating and it can be evaluated
                expect(getAverageRating()).toBeLessThan(config.CDP_WATCHER_DISABLED_RATING_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.disabledForPeriod)
            })

            it('should go to disabledIndefinitely with enough bad states', () => {
                updateState(
                    [],
                    [
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                    ]
                )
                expect(currentState()).toBe(HogWatcherState.overflowed)
                updateState([0.2, 0.2, 0.2, 0.2], [])
                expect(currentState()).toBe(HogWatcherState.disabledIndefinitely)
            })
        })

        describe('3 - disabledForPeriod', () => {
            it('should stay disabled for period until the period has passed ', () => {
                updateState([], [HogWatcherState.disabledForPeriod])
                expect(currentState()).toBe(HogWatcherState.disabledForPeriod)
                expect(states).toEqual([
                    { state: HogWatcherState.disabledForPeriod, timestamp: periodTimestamp(config) },
                ])
                advanceTime(config.CDP_WATCHER_DISABLED_PERIOD - 1)
                expect(currentState()).toBe(HogWatcherState.disabledForPeriod)
                advanceTime(2)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })
        })

        describe('4 - disabledIndefinitely', () => {
            it('should stay in disabledIndefinitely no matter what', () => {
                updateState([], [HogWatcherState.disabledIndefinitely])

                expect(currentState()).toBe(HogWatcherState.disabledIndefinitely)
                // Technically this wouldn't be possible but still good to test
                updateState([1, 1, 1, 1, 1, 1, 1], [])
                expect(currentState()).toBe(HogWatcherState.disabledIndefinitely)
            })
        })
    })
})
