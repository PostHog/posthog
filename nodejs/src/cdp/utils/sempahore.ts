export class Semaphore {
    private waiting: Array<() => void> = []

    constructor(private permits: number) {}

    private async acquire(): Promise<void> {
        if (this.permits > 0) {
            this.permits--
            return
        }
        return new Promise<void>((resolve) => this.waiting.push(resolve))
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

    async run<T>(func: () => Promise<T>): Promise<T> {
        await this.acquire()
        try {
            return await func()
        } finally {
            this.release()
        }
    }
}
