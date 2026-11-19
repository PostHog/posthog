import { BatchCoalescer } from './batch-coalescer'

describe('BatchCoalescer', () => {
    let processed: number[][]
    let settled: string[]

    const coalescer = (windowMs: number, maxBatches: number, fail?: Error): BatchCoalescer<number> =>
        new BatchCoalescer<number>(
            (items) => {
                processed.push(items)
                return fail ? Promise.reject(fail) : Promise.resolve()
            },
            windowMs,
            maxBatches
        )

    const track = (name: string, promise: Promise<void>): Promise<void> =>
        promise.then(
            () => void settled.push(`${name}:ok`),
            () => void settled.push(`${name}:failed`)
        )

    beforeEach(() => {
        jest.useFakeTimers()
        processed = []
        settled = []
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        { name: 'with no window', windowMs: 0, maxBatches: 3 },
        { name: 'when the consumer allows one unsettled batch', windowMs: 200, maxBatches: 1 },
    ])('processes every batch on its own $name', async ({ windowMs, maxBatches }) => {
        const batches = coalescer(windowMs, maxBatches)

        await Promise.all([batches.add([1]), batches.add([2])])

        expect(processed).toEqual([[1], [2]])
    })

    it('processes the batches that arrive within the window together, and settles them all after', async () => {
        const batches = coalescer(200, 5)
        const first = track('first', batches.add([1, 2]))
        await jest.advanceTimersByTimeAsync(150)
        const second = track('second', batches.add([3]))

        await jest.advanceTimersByTimeAsync(49)
        expect(processed).toEqual([])
        expect(settled).toEqual([])

        await jest.advanceTimersByTimeAsync(1)
        await Promise.all([first, second])
        expect(processed).toEqual([[1, 2, 3]])
        expect(settled).toEqual(['first:ok', 'second:ok'])
    })

    it('processes the group as soon as it holds the most batches the consumer leaves unsettled', async () => {
        const batches = coalescer(10_000, 2)

        await Promise.all([batches.add([1]), batches.add([2])])

        expect(processed).toEqual([[1, 2]])
    })

    it('settles an empty batch at once when nothing is waiting, without processing anything', async () => {
        const batches = coalescer(200, 3)

        await batches.add([])

        expect(processed).toEqual([])
    })

    it('holds an empty batch behind the group before it, and counts it toward the limit', async () => {
        const batches = coalescer(10_000, 2)
        const first = track('first', batches.add([1]))
        const empty = track('empty', batches.add([]))

        await Promise.all([first, empty])

        expect(processed).toEqual([[1]])
        expect(settled).toEqual(['first:ok', 'empty:ok'])
    })

    it('fails every batch of a group whose processing fails, so none of them is committed', async () => {
        const batches = coalescer(200, 5, new Error('cyclotron is down'))
        const first = track('first', batches.add([1]))
        const second = track('second', batches.add([2]))

        await jest.advanceTimersByTimeAsync(200)
        await Promise.all([first, second])

        expect(settled).toEqual(['first:failed', 'second:failed'])
    })

    it('processes the waiting group at once on flush, and starts a new group after it', async () => {
        const batches = coalescer(10_000, 5)
        const first = batches.add([1])

        batches.flush()
        await first
        const second = batches.add([2])
        batches.flush()
        await second

        expect(processed).toEqual([[1], [2]])
    })
})
