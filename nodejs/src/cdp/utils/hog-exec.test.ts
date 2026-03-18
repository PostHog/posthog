import { compileHog } from '../templates/compiler'
import { execHog } from './hog-exec'

describe('hog-exec', () => {
    describe('thread relief', () => {
        jest.setTimeout(10000)
        let interval: NodeJS.Timeout

        let lastCheck = Date.now()
        let longestDelay = 0
        const blockTime = 100

        beforeEach(() => {
            jest.spyOn(Date, 'now').mockRestore()
            jest.useRealTimers()

            interval = setInterval(() => {
                // Sets up an interval loop so we can see how long the longest delay between ticks is
                longestDelay = Math.max(longestDelay, Date.now() - lastCheck)
                lastCheck = Date.now()
            }, 0)
        })

        afterEach(() => {
            clearInterval(interval)
        })

        it('should process batches in a way that does not block the main thread', async () => {
            const evilFunctionCode = await compileHog(`
                fn fibonacci(number) {
                    print('I AM FIBONACCI. ')
                    if (number < 2) {
                        return number;
                    } else {
                        return fibonacci(number - 1) + fibonacci(number - 2);
                    }
                }
                print(f'fib {fibonacci(64)}');
            `)

            const numberToTest = 10

            const results = await Promise.all(
                Array.from({ length: numberToTest }, () =>
                    execHog(evilFunctionCode, {
                        timeout: blockTime,
                        functions: {
                            print: () => {},
                        },
                    })
                )
            )

            const timings = results.map((r) => r.durationMs)
            const reliefs = results.map((r) => r.waitedForThreadRelief)
            const total = timings.reduce((x, y) => x + y, 0)
            // Every one of these should have triggered a thread relief
            expect(reliefs.every((r) => r)).toBe(true)

            // Timings is semi random so we can't test for exact values
            expect(total).toBeGreaterThan(100 * numberToTest)
            expect(total).toBeLessThan(200 * numberToTest) // the hog exec limiter isn't exact
            await new Promise((resolve) => setTimeout(resolve, 1))
            expect(longestDelay).toBeLessThan(blockTime * 2) // Rough upper bound of the hog exec limiter (2x the block time)
        })

        it('should only trigger thread relief if necessary', async () => {
            const blockTime = 100

            const evilFunctionCode = await compileHog(`
                fn fibonacci(number) {
                    print('I AM FIBONACCI. ')
                    if (number < 2) {
                        return number;
                    } else {
                        return fibonacci(number - 1) + fibonacci(number - 2);
                    }
                }
                print(f'fib {fibonacci(64)}');
            `)

            const simpleCode = await compileHog(`
                print('I AM SIMPLE.')
            `)

            const toTest = [
                evilFunctionCode,
                simpleCode,
                simpleCode,
                simpleCode,
                simpleCode,
                simpleCode,
                evilFunctionCode,
                simpleCode,
                simpleCode,
                simpleCode,
                evilFunctionCode,
            ]

            const results = await Promise.all(
                toTest.map((code) =>
                    execHog(code, {
                        timeout: blockTime,
                        functions: {
                            print: () => {},
                        },
                    })
                )
            )

            const timings = results.map((r) => r.durationMs)
            const reliefs = results.map((r) => r.waitedForThreadRelief)
            const total = timings.reduce((x, y) => x + y, 0)
            // Every one of these should have triggered a thread relief
            expect(reliefs).toEqual([
                true, // evil function
                false,
                false,
                false,
                false,
                false,
                true, // evil function
                false,
                false,
                false,
                true, // evil function
            ])

            // Timings is semi random so we can't test for exact values
            expect(total).toBeGreaterThan(100 * 3) // The 3 slow ones
            expect(total).toBeLessThan(200 * 3) // Double the 3 slow ones
            await new Promise((resolve) => setTimeout(resolve, 1))
            expect(longestDelay).toBeLessThan(blockTime * 2) // Rough upper bound of the hog exec limiter (2x the block time)
        })
    })
})
