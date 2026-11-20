import { perElement } from './per-element-step'
import { ok } from './results'

describe('perElement', () => {
    it('keeps input order and never runs more than maxConcurrency steps at once', async () => {
        let running = 0
        let peak = 0
        const started: number[] = []
        const step = perElement(
            async (value: number) => {
                started.push(value)
                running++
                peak = Math.max(peak, running)
                // Later values wait fewer ticks and finish first, so output order cannot follow completion order.
                for (let tick = 0; tick < 8 - value; tick++) {
                    await new Promise((resolve) => setImmediate(resolve))
                }
                running--
                return ok(value * 10)
            },
            { maxConcurrency: 3 }
        )

        const results = await step([1, 2, 3, 4, 5, 6, 7])

        expect(results).toEqual([1, 2, 3, 4, 5, 6, 7].map((value) => ok(value * 10)))
        expect(peak).toBe(3)
        expect(started).toEqual([1, 2, 3, 4, 5, 6, 7])
    })
})
