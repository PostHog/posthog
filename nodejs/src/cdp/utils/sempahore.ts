export class Semaphore {
    private waiting = new Set<() => void>()

    constructor(private permits: number) {}

    private async acquire(signal?: AbortSignal): Promise<void> {
        if (this.permits > 0) {
            this.permits--
            return
        }
        signal?.throwIfAborted()
        return new Promise<void>((resolve, reject) => {
            const onAbort = (): void => {
                this.waiting.delete(grant)
                reject(signal!.reason)
            }
            const grant = (): void => {
                signal?.removeEventListener('abort', onAbort)
                resolve()
            }
            signal?.addEventListener('abort', onAbort, { once: true })
            this.waiting.add(grant)
        })
    }

    private release(): void {
        const next = this.waiting.values().next()
        if (next.done) {
            this.permits++
            return
        }
        this.waiting.delete(next.value)
        next.value()
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
