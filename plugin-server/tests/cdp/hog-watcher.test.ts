import { HogWatcherObservationPeriod, HogWatcherObserver } from '../../src/cdp/hog-watcher'

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
                const res = observer.addObservations(vals)
                expect(res.rating).toBe(rating)
            })
        })
    })
})
