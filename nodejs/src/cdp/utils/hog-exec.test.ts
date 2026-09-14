import { configureEventLoopYield, getEventLoopYieldThresholdMs } from '~/common/utils/event-loop-yield'
import { startEventLoopObserver } from '~/tests/helpers/event-loop'

import { compileHog } from '../templates/compiler'
import { execHog } from './hog-exec'

describe('hog-exec', () => {
    describe('thread relief', () => {
        jest.setTimeout(10000)

        const blockTimeMs = 50
        let originalThresholdMs: number

        beforeEach(() => {
            jest.spyOn(Date, 'now').mockRestore()
            jest.useRealTimers()

            originalThresholdMs = getEventLoopYieldThresholdMs()
            configureEventLoopYield(blockTimeMs / 2)
        })

        afterEach(() => {
            configureEventLoopYield(originalThresholdMs)
        })

        it('lets the event loop run between hog executions', async () => {
            // Never returns, so each execution runs until the timeout stops it.
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

            const numberToTest = 5
            const observer = startEventLoopObserver()

            await Promise.all(
                Array.from({ length: numberToTest }, () =>
                    execHog(evilFunctionCode, {
                        timeout: blockTimeMs,
                        functions: {
                            print: () => {},
                        },
                    })
                )
            )

            // Every execution blocks past the yield threshold, so each one must
            // hand the loop back. Without yielding the count would be zero.
            expect(observer.stop()).toBeGreaterThanOrEqual(numberToTest)
        })
    })
})
