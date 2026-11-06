import { Semaphore, SemaphoreWaitExpired } from './sempahore'

const settleSoon = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

describe('Semaphore', () => {
    it('runs at most its permits at once and hands a freed permit to the next waiter', async () => {
        const slots = new Semaphore(2)
        const finish: (() => void)[] = []
        const started: number[] = []
        const never = new Promise<void>(() => {})
        const runs = [0, 1, 2, 3].map((i) =>
            slots.run(() => {
                started.push(i)
                return new Promise<void>((resolve) => finish.push(resolve))
            }, never)
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
        await expect(Promise.all(runs)).resolves.toEqual([undefined, undefined, undefined, undefined])
    })

    it('gives up without running when its give-up signal settles before a permit frees, and leaves no permit taken', async () => {
        const slots = new Semaphore(1)
        let releaseFirst!: () => void
        const first = slots.run(() => new Promise<void>((resolve) => (releaseFirst = resolve)))
        let expire!: () => void
        const deadline = new Promise<void>((resolve) => (expire = resolve))
        const late = jest.fn(() => Promise.resolve())
        const waiting = slots.run(late, deadline)

        expire()
        await expect(waiting).rejects.toThrow(SemaphoreWaitExpired)
        expect(late).not.toHaveBeenCalled()

        releaseFirst()
        await first
        const next = jest.fn(() => Promise.resolve())
        await slots.run(next)
        expect(next).toHaveBeenCalled()
    })

    it('keeps the permit of a running call past its give-up signal until the call settles', async () => {
        const slots = new Semaphore(1)
        let expire!: () => void
        let releaseStalled!: () => void
        const stalled = slots.run(
            () => new Promise<void>((resolve) => (releaseStalled = resolve)),
            new Promise<void>((resolve) => (expire = resolve))
        )
        await settleSoon()
        expire()

        let expireWaiter!: () => void
        const waiter = jest.fn(() => Promise.resolve())
        const waiting = slots.run(waiter, new Promise<void>((resolve) => (expireWaiter = resolve)))
        await settleSoon()
        expect(waiter).not.toHaveBeenCalled()

        releaseStalled()
        await stalled
        await waiting
        expect(waiter).toHaveBeenCalled()
        expireWaiter()
    })
})
