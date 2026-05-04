import { configureEventLoopYield, getEventLoopYieldThresholdMs } from '../../utils/event-loop-yield'
import { compileHog } from '../templates/compiler'
import { execHog } from './hog-exec'

describe('hog-exec', () => {
    describe('thread relief', () => {
        jest.setTimeout(10000)
        let interval: NodeJS.Timeout

        let lastCheck = Date.now()
        let longestDelay = 0
        const blockTime = 100
        let originalThresholdMs: number

        beforeEach(() => {
            jest.spyOn(Date, 'now').mockRestore()
            jest.useRealTimers()

            originalThresholdMs = getEventLoopYieldThresholdMs()
            configureEventLoopYield(blockTime)

            interval = setInterval(() => {
                // Sets up an interval loop so we can see how long the longest delay between ticks is
                longestDelay = Math.max(longestDelay, Date.now() - lastCheck)
                lastCheck = Date.now()
            }, 0)
        })

        afterEach(() => {
            clearInterval(interval)
            configureEventLoopYield(originalThresholdMs)
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
            const total = timings.reduce((x, y) => x + y, 0)

            // Timings is semi random so we can't test for exact values
            expect(total).toBeGreaterThan(100 * numberToTest)
            expect(total).toBeLessThan(200 * numberToTest) // the hog exec limiter isn't exact
            await new Promise((resolve) => setTimeout(resolve, 1))
            // Rough upper bound: with the semaphore serializing calls, the
            // event loop should not be starved for more than ~2.5× one block.
            // (If yielding were broken, this would be ~10× the block.)
            expect(longestDelay).toBeLessThan(blockTime * 2.5)
        })
    })
})
