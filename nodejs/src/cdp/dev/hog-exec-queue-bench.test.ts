import { configureEventLoopYield, getEventLoopYieldThresholdMs } from '~/common/utils/event-loop-yield'

import { execHog } from '../utils/hog-exec'

describe('hog render queue benchmark', () => {
    const CEILING_MS = 1000
    const leaf = ['_H', 1, 32, 'x']

    it('queues and drops 50,000 renders that share a deadline under the ceiling', async () => {
        const threshold = getEventLoopYieldThresholdMs()
        configureEventLoopYield(0)
        jest.useFakeTimers({
            doNotFake: [
                'hrtime',
                'nextTick',
                'queueMicrotask',
                'setImmediate',
                'clearImmediate',
                'setInterval',
                'clearInterval',
                'Date',
            ],
        })
        const nextTurn = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))
        try {
            let first: Awaited<ReturnType<typeof execHog>> | undefined
            void execHog(leaf).then((outcome) => (first = outcome))
            for (let turn = 0; jest.getTimerCount() === 0 && turn < 1000; turn++) {
                await nextTurn()
            }
            const deadline = new AbortController()
            const queuedAt = process.hrtime.bigint()
            const queued = Array.from({ length: 50_000 }, () => execHog(leaf, undefined, deadline.signal))
            const queueMs = Number(process.hrtime.bigint() - queuedAt) / 1_000_000
            await nextTurn()

            const abortedAt = process.hrtime.bigint()
            deadline.abort(new DOMException('The deadline passed', 'TimeoutError'))
            const abortMs = Number(process.hrtime.bigint() - abortedAt) / 1_000_000
            const outcomes = await Promise.all(queued)

            expect(outcomes.every((outcome) => outcome.error?.name === 'TimeoutError')).toBe(true)
            expect(queueMs).toBeLessThan(CEILING_MS)
            expect(abortMs).toBeLessThan(CEILING_MS)
            for (let turn = 0; first === undefined && turn < 1000; turn++) {
                jest.runOnlyPendingTimers()
                await nextTurn()
            }
            expect(first?.execResult?.result).toBe('x')
        } finally {
            jest.useRealTimers()
            configureEventLoopYield(threshold)
        }
    })
})
