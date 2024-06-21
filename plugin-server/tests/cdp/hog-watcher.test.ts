import {
    DISABLE_THRESHOLD,
    DISABLED_PERIOD,
    HogWatcherObservationPeriodDetailed,
    HogWatcherObserver,
    HogWatcherState,
    OBSERVATION_PERIOD,
    OVERFLOW_THRESHOLD,
} from '../../src/cdp/hog-watcher'

describe('HogWatcher', () => {
    describe('HogWatcherObserver', () => {
        describe('observations', () => {
            let observer: HogWatcherObserver

            beforeEach(() => {
                observer = new HogWatcherObserver('1')
            })

            it('should update the observation', () => {
                expect(observer.observations).toEqual([])

                observer.addObservations({
                    successes: 10,
                    failures: 1,
                    asyncFunctionFailures: 2,
                    asyncFunctionSuccesses: 3,
                })

                expect(observer.observations).toMatchObject([
                    {
                        timestamp: Math.floor(Date.now() / 10000) * 10000,
                        successes: 10,
                        failures: 1,
                        asyncFunctionFailures: 2,
                        asyncFunctionSuccesses: 3,
                    },
                ])

                observer.addObservations({
                    asyncFunctionSuccesses: 11,
                })

                expect(observer.observations).toMatchObject([
                    {
                        timestamp: Math.floor(Date.now() / 10000) * 10000,
                        successes: 10,
                        failures: 1,
                        asyncFunctionFailures: 2,
                        asyncFunctionSuccesses: 14,
                    },
                ])
            })

            // TODO: Change rating to account for numbers as well - low volume failures can still have a high rating as their impact is not so bad
            const cases: Array<[Partial<HogWatcherObservationPeriodDetailed>, number]> = [
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
                const res = observer.addObservations(vals)
                expect(res.rating).toBe(rating)
            })
        })

        describe('states', () => {
            let now: number
            beforeEach(() => {
                now = Date.now()

                jest.useFakeTimers()
                jest.setSystemTime(now)
            })

            afterEach(() => {
                jest.useRealTimers()
            })

            const advanceTime = (ms: number) => {
                jest.advanceTimersByTime(ms)
            }

            const updateObserver = (observer: HogWatcherObserver, ratings: number[], states: HogWatcherState[]) => {
                states.forEach((state) => {
                    observer.states.push({
                        timestamp: Date.now(),
                        state,
                    })
                })

                ratings.forEach((rating) => {
                    advanceTime(OBSERVATION_PERIOD)
                    observer.addObservations({
                        // Simulate rating as ratio of success and failures
                        successes: 1000 * rating,
                        failures: 1000 * (1 - rating),
                    })
                })
            }

            const createObserver = (ratings: number[] = [], states: HogWatcherState[] = []): HogWatcherObserver => {
                const observer = new HogWatcherObserver('1')
                updateObserver(observer, ratings, states)
                return observer
            }

            describe('1 - healthy', () => {
                it('should be healthy with no observations or previous states', () => {
                    const observer = createObserver([])
                    expect(observer.currentState()).toBe(HogWatcherState.healthy)
                })

                it.each(Object.values(HogWatcherState))(
                    'should be whatever the last state is (%s) if no observations',
                    (lastState) => {
                        const observer = createObserver([], [lastState as any])
                        expect(observer.currentState()).toBe(lastState)
                    }
                )

                it('should not change if too few observations', () => {
                    const observer = createObserver([0, 0])
                    expect(observer.averageRating()).toEqual(0)
                    expect(observer.currentState()).toBe(HogWatcherState.healthy)
                })

                it('should move to overflow if enough observations are unhealthy', () => {
                    const observer = createObserver([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6])
                    expect(observer.states).toMatchObject([])
                    expect(observer.averageRating()).toBeLessThan(OVERFLOW_THRESHOLD)
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)
                    expect(observer.states).toMatchObject([{ state: HogWatcherState.overflowed }])
                })
            })

            describe('2 - overflow', () => {
                it('should stay in overflow if the rating does not change ', () => {
                    const observer = createObserver([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6])
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)
                    expect(observer.averageRating()).toBeLessThan(OVERFLOW_THRESHOLD)
                    expect(observer.averageRating()).toBeGreaterThan(DISABLE_THRESHOLD)

                    updateObserver(observer, [0.5, 0.5, 0.6, 0.7, 0.8, 1, 0.8], [])
                    expect(observer.averageRating()).toBeLessThan(OVERFLOW_THRESHOLD)
                    expect(observer.averageRating()).toBeGreaterThan(DISABLE_THRESHOLD)
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)
                })

                it('should move back to healthy with enough healthy activity ', () => {
                    const observer = createObserver([], [HogWatcherState.overflowed])
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)
                    updateObserver(observer, [0.5, 0.8, 0.9, 0.9, 1, 0.9, 1], [])
                    expect(observer.averageRating()).toBeGreaterThan(OVERFLOW_THRESHOLD)
                    expect(observer.currentState()).toBe(HogWatcherState.healthy)
                })

                it('should move to overflow if enough observations are unhealthy', () => {
                    const observer = createObserver([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6])
                    expect(observer.states).toMatchObject([])
                    expect(observer.averageRating()).toBeLessThan(OVERFLOW_THRESHOLD)
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)
                    expect(observer.states).toMatchObject([{ state: HogWatcherState.overflowed }])
                })

                it('should move to disabledForPeriod if sustained lower', () => {
                    const observer = createObserver([], [HogWatcherState.overflowed])
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)

                    updateObserver(observer, [0.5, 0.4, 0.4, 0.2], [])
                    expect(observer.averageRating()).toBeLessThan(DISABLE_THRESHOLD)
                    expect(observer.currentState()).toBe(HogWatcherState.disabledForPeriod)
                })

                it('should go to disabledIndefinitely with enough bad states', () => {
                    const observer = createObserver(
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
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)
                    updateObserver(observer, [0.2, 0.2, 0.2, 0.2], [])
                    expect(observer.currentState()).toBe(HogWatcherState.disabledIndefinitely)
                })
            })

            describe('3 - disabledForPeriod', () => {
                it('should stay disabled for period until the period has passed ', () => {
                    const observer = createObserver([], [HogWatcherState.disabledForPeriod])
                    expect(observer.currentState()).toBe(HogWatcherState.disabledForPeriod)
                    expect(observer.states).toEqual([{ state: HogWatcherState.disabledForPeriod, timestamp: now }])
                    advanceTime(DISABLED_PERIOD - 1)
                    expect(observer.currentState()).toBe(HogWatcherState.disabledForPeriod)
                    advanceTime(2)
                    expect(observer.currentState()).toBe(HogWatcherState.overflowed)
                    expect(observer.states).toEqual([
                        { state: HogWatcherState.disabledForPeriod, timestamp: now },
                        { state: HogWatcherState.overflowed, timestamp: now + DISABLED_PERIOD + 1 },
                    ])
                })
            })

            describe('4 - disabledIndefinitely', () => {
                it('should stay in disabledIndefinitely no matter what', () => {
                    const observer = createObserver([], [HogWatcherState.disabledIndefinitely])

                    expect(observer.currentState()).toBe(HogWatcherState.disabledIndefinitely)
                    // Technically this wouldn't be possible but still good to test
                    updateObserver(observer, [1, 1, 1, 1, 1, 1, 1], [])
                    expect(observer.currentState()).toBe(HogWatcherState.disabledIndefinitely)
                })
            })
        })
    })
})
