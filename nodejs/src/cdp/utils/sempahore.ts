export class SemaphoreWaitExpired extends Error {
    constructor() {
        super('Gave up waiting for a semaphore permit')
    }
}

export class Semaphore {
    private waiting: Array<() => void> = []

    constructor(private permits: number) {}

    private async acquire(giveUp?: Promise<void>): Promise<void> {
        if (this.permits > 0) {
            this.permits--
            return
        }
        return new Promise<void>((resolve, reject) => {
            this.waiting.push(resolve)
            void giveUp?.then(() => {
                const index = this.waiting.indexOf(resolve)
                if (index !== -1) {
                    this.waiting.splice(index, 1)
                    reject(new SemaphoreWaitExpired())
                }
            })
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

    // A caller that settles `giveUp` while still waiting leaves the queue without running `func`; once
    // `func` runs, it keeps its permit until it settles.
    async run<T>(func: () => Promise<T>, giveUp?: Promise<void>): Promise<T> {
        await this.acquire(giveUp)
        try {
            return await func()
        } finally {
            this.release()
        }
    }
}
