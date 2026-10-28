import { configureEventLoopYield, getEventLoopYieldThresholdMs } from '~/common/utils/event-loop-yield'

import { compileHog } from '../templates/compiler'
import { execHog } from './hog-exec'

describe('hog-exec', () => {
    describe('thread relief', () => {
        jest.setTimeout(10000)
        let interval: NodeJS.Timeout
        let timerTicks = 0
        const blockTime = 100
        let originalThresholdMs: number

        beforeEach(() => {
            jest.spyOn(Date, 'now').mockRestore()
            jest.useRealTimers()

            originalThresholdMs = getEventLoopYieldThresholdMs()
            configureEventLoopYield(blockTime)

            interval = setInterval(() => {
                timerTicks++
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
            const timerTicksAtStart: number[] = []

            const results = await Promise.all(
                Array.from({ length: numberToTest }, (_, index) =>
                    execHog(evilFunctionCode, {
                        timeout: blockTime,
                        functions: {
                            print: () => {
                                timerTicksAtStart[index] ??= timerTicks
                            },
                        },
                    })
                )
            )

            const timings = results.map((r) => r.durationMs)
            const total = timings.reduce((x, y) => x + y, 0)

            // Timings is semi random so we can't test for exact values
            expect(total).toBeGreaterThan(100 * numberToTest)
            expect(total).toBeLessThan(200 * numberToTest) // the hog exec limiter isn't exact
            // A timer callback runs between every two executions. Without yielding, all executions
            // run in one macrotask and see the same tick count.
            expect(new Set(timerTicksAtStart).size).toBe(numberToTest)
        })
    })
})
