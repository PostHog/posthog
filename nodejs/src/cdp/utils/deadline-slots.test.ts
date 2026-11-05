import { DeadlineSlots } from './deadline-slots'

const settleSoon = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

describe('DeadlineSlots', () => {
    it('runs at most its size at once and hands a freed slot to the next waiter', async () => {
        const slots = new DeadlineSlots(2)
        const finish: (() => void)[] = []
        const started: number[] = []
        const never = new Promise<void>(() => {})
        const runs = [0, 1, 2, 3].map((i) =>
            slots.run(never, () => {
                started.push(i)
                return new Promise<void>((resolve) => finish.push(resolve))
            })
        )

        await settleSoon()
        expect(started).toEqual([0, 1])

        finish[0]()
        await settleSoon()
        expect(started).toEqual([0, 1, 2])

        finish[1]()
        finish[2]()
        await settleSoon()
        finish[3]()
        await expect(Promise.all(runs)).resolves.toEqual([true, true, true, true])
    })

    it('gives up without running when the deadline settles before a slot frees, and leaves no slot taken', async () => {
        const slots = new DeadlineSlots(1)
        let releaseFirst!: () => void
        const first = slots.run(
            new Promise<void>(() => {}),
            () => new Promise<void>((resolve) => (releaseFirst = resolve))
        )
        let expire!: () => void
        const deadline = new Promise<void>((resolve) => (expire = resolve))
        const late = jest.fn(() => Promise.resolve())
        const waiting = slots.run(deadline, late)

        expire()
        await expect(waiting).resolves.toBe(false)
        expect(late).not.toHaveBeenCalled()

        releaseFirst()
        await expect(first).resolves.toBe(true)
        const next = jest.fn(() => Promise.resolve())
        await expect(slots.run(new Promise<void>(() => {}), next)).resolves.toBe(true)
        expect(next).toHaveBeenCalled()
    })

    it('keeps the slot of a running call past its deadline until the call settles', async () => {
        const slots = new DeadlineSlots(1)
        let expire!: () => void
        let releaseStalled!: () => void
        const stalled = slots.run(
            new Promise<void>((resolve) => (expire = resolve)),
            () => new Promise<void>((resolve) => (releaseStalled = resolve))
        )
        await settleSoon()
        expire()

        let expireWaiter!: () => void
        const waiter = jest.fn(() => Promise.resolve())
        const waiting = slots.run(new Promise<void>((resolve) => (expireWaiter = resolve)), waiter)
        await settleSoon()
        expect(waiter).not.toHaveBeenCalled()

        releaseStalled()
        await stalled
        await expect(waiting).resolves.toBe(true)
        expect(waiter).toHaveBeenCalled()
        expireWaiter()
    })
})
