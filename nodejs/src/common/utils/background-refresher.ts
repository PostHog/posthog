import { logger } from './logger'

// A background refresher will act like a TTL cache but choosing to refresh the value in the background rather than
// dropping the data or blocking the request.
export class BackgroundRefresher<T> {
    private cachedValue: T | undefined = undefined
    private cachedValuePromise: Promise<T> | null = null
    private lastRefreshTime = 0

    constructor(
        private readonly refreshFunction: () => Promise<T>,
        private readonly maxAgeMs: number = 1000 * 60,
        private readonly errorHandler: (e: unknown) => void = (e) => {
            throw e
        }
    ) {}

    public async refresh(): Promise<T> {
        if (this.cachedValuePromise) {
            return this.cachedValuePromise
        }
        try {
            this.cachedValuePromise = this.refreshFunction()
            this.cachedValue = await this.cachedValuePromise
        } catch (e) {
            logger.error('BackgroundRefresher: Error refreshing background task', e)
            throw e
        } finally {
            this.cachedValuePromise = null
            this.lastRefreshTime = Date.now()
        }

        return this.cachedValue
    }

    public async get(): Promise<T> {
        if (!this.cachedValue) {
            await this.refresh()
        }
        this.refreshIfStale()
        return this.cachedValue!
    }

    /**
     * Returns the cached value, or undefined if not yet loaded.
     * Triggers a background refresh if the cache is stale or empty.
     */
    public tryGet(): T | undefined {
        this.refreshIfStale()
        return this.cachedValue
    }

    private refreshIfStale(): void {
        if (!this.cachedValue || Date.now() - this.lastRefreshTime > this.maxAgeMs) {
            void this.refresh().catch(this.errorHandler)
        }
    }
}
