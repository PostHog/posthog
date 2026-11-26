interface Waiter {
    resolve: () => void
    reject: (reason: unknown) => void
    signal?: AbortSignal
}

interface SignalWaiters {
    waiters: Set<Waiter>
    onAbort: () => void
}

export class Semaphore {
    private waiting = new Set<Waiter>()
    private waitingBySignal = new Map<AbortSignal, SignalWaiters>()

    constructor(private permits: number) {}

    private async acquire(signal?: AbortSignal): Promise<void> {
        if (this.permits > 0) {
            this.permits--
            return
        }
        signal?.throwIfAborted()
        return new Promise<void>((resolve, reject) => {
            const waiter = { resolve, reject, signal }
            this.waiting.add(waiter)
            if (signal) {
                this.watch(signal, waiter)
            }
        })
    }

    private watch(signal: AbortSignal, waiter: Waiter): void {
        let group = this.waitingBySignal.get(signal)
        if (!group) {
            const waiters = new Set<Waiter>()
            const onAbort = (): void => {
                this.waitingBySignal.delete(signal)
                for (const aborted of waiters) {
                    this.waiting.delete(aborted)
                    aborted.reject(signal.reason)
                }
            }
            group = { waiters, onAbort }
            this.waitingBySignal.set(signal, group)
            signal.addEventListener('abort', onAbort, { once: true })
        }
        group.waiters.add(waiter)
    }

    private unwatch(waiter: Waiter): void {
        if (!waiter.signal) {
            return
        }
        const group = this.waitingBySignal.get(waiter.signal)
        if (!group) {
            return
        }
        group.waiters.delete(waiter)
        if (group.waiters.size === 0) {
            waiter.signal.removeEventListener('abort', group.onAbort)
            this.waitingBySignal.delete(waiter.signal)
        }
    }

    private release(): void {
        const next = this.waiting.values().next()
        if (next.done) {
            this.permits++
            return
        }
        this.waiting.delete(next.value)
        this.unwatch(next.value)
        next.value.resolve()
    }

    async run<T>(func: () => Promise<T>, signal?: AbortSignal): Promise<T> {
        await this.acquire(signal)
        try {
            return await func()
        } finally {
            this.release()
        }
    }
}
