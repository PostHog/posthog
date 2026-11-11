export class Semaphore {
    private waiting: Array<() => void> = []

    constructor(private permits: number) {}

    private async acquire(signal?: AbortSignal): Promise<void> {
        if (this.permits > 0) {
            this.permits--
            return
        }
        signal?.throwIfAborted()
        return new Promise<void>((resolve, reject) => {
            const onAbort = (): void => {
                this.waiting = this.waiting.filter((waiter) => waiter !== grant)
                reject(signal!.reason)
            }
            const grant = (): void => {
                signal?.removeEventListener('abort', onAbort)
                resolve()
            }
            signal?.addEventListener('abort', onAbort, { once: true })
            this.waiting.push(grant)
        })
    }

    private release(): void {
        if (this.waiting.length > 0) {
            const next = this.waiting.shift()
            if (next) {
                next()
            }
        } else {
            this.permits++
        }
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
