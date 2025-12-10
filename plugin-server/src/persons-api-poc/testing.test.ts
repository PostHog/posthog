import { SequenceExecutor, createBreakpoint, createTestSequence } from './testing'

describe('createBreakpoint', () => {
    it('wait blocks until complete is called', async () => {
        const bp = createBreakpoint<number>()
        let resolved = false

        const waitPromise = bp.wait.then((value) => {
            resolved = true
            return value
        })

        expect(resolved).toBe(false)

        bp.complete(42)

        const result = await waitPromise
        expect(resolved).toBe(true)
        expect(result).toBe(42)
    })

    it('works with void type', async () => {
        const bp = createBreakpoint()
        let resolved = false

        const waitPromise = bp.wait.then(() => {
            resolved = true
        })

        expect(resolved).toBe(false)

        bp.complete(undefined)

        await waitPromise
        expect(resolved).toBe(true)
    })
})

describe('SequenceExecutor', () => {
    it('executes breakpoints in order', async () => {
        const executor = new SequenceExecutor()
        const order: number[] = []

        const bp1 = createBreakpoint()
        const bp2 = createBreakpoint()
        const bp3 = createBreakpoint()

        executor.add(bp1)
        executor.add(bp2)
        executor.add(bp3)

        const runPromise = executor.run()

        setTimeout(() => {
            order.push(1)
            bp1.complete(undefined)
        }, 10)

        setTimeout(() => {
            order.push(2)
            bp2.complete(undefined)
        }, 20)

        setTimeout(() => {
            order.push(3)
            bp3.complete(undefined)
        }, 30)

        await runPromise

        expect(order).toEqual([1, 2, 3])
    })

    it('waits for each breakpoint before proceeding', async () => {
        const executor = new SequenceExecutor()
        const events: string[] = []

        const bp1 = createBreakpoint()
        const bp2 = createBreakpoint()

        executor.add(bp1)
        executor.add(bp2)

        const runPromise = executor.run()

        // Complete bp2 first
        bp2.complete(undefined)
        events.push('bp2 completed')

        // Small delay to ensure executor hasn't moved past bp1
        await new Promise((resolve) => setTimeout(resolve, 5))
        events.push('after delay')

        // Now complete bp1
        bp1.complete(undefined)
        events.push('bp1 completed')

        await runPromise
        events.push('run finished')

        expect(events).toEqual(['bp2 completed', 'after delay', 'bp1 completed', 'run finished'])
    })
})

describe('createTestSequence', () => {
    it('creates executor from array of wait promises', async () => {
        const bp1 = createBreakpoint()
        const bp2 = createBreakpoint()
        const bp3 = createBreakpoint()

        const executor = createTestSequence([bp1.wait, bp2.wait, bp3.wait])

        let finished = false
        const runPromise = executor.run().then(() => {
            finished = true
        })

        expect(finished).toBe(false)

        bp1.complete(undefined)
        await Promise.resolve()
        expect(finished).toBe(false)

        bp2.complete(undefined)
        await Promise.resolve()
        expect(finished).toBe(false)

        bp3.complete(undefined)
        await runPromise
        expect(finished).toBe(true)
    })
})
