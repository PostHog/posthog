export class Semaphore {
    private waiting: Array<() => void> = []

    constructor(private permits: number) {}

    async acquire(): Promise<void> {
        if (this.permits > 0) {
            this.permits--
            return
        }
        return new Promise<void>((resolve) => this.waiting.push(resolve))
    }

    release(): void {
        if (this.waiting.length > 0) {
            const next = this.waiting.shift()
            if (next) {
                next()
            }
        } else {
            this.permits++
        }
    }

    async withLock<T>(func: () => Promise<T>): Promise<T> {
        await this.acquire()
        try {
            return await func()
        } finally {
            this.release()
        }
    }
}
