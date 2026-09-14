import { logger } from './logger'

// A background refresher will act like a TTL cache but choosing to refresh the value in the background rather than
// dropping the data or blocking the request.
export class BackgroundRefresher<T> {
    private cachedValue: T | undefined = undefined
    private cachedValuePromise: Promise<T> | null = null
    private lastRefreshTime = 0
    private currentMaxAgeMs: number

    constructor(
        private readonly refreshFunction: () => Promise<T>,
        private readonly maxAgeMs: number = 1000 * 60,
        private readonly errorHandler: (e: unknown) => void = (e) => {
            throw e
        },
        // Upper bound of a random age added on top of maxAgeMs, drawn again after every refresh.
        // Many processes that start together otherwise refresh in lockstep and hit the source at
        // the same moments.
        private readonly jitterMs: number = 0
    ) {
        this.currentMaxAgeMs = this.nextMaxAgeMs()
    }

    private nextMaxAgeMs(): number {
        return this.maxAgeMs + Math.random() * this.jitterMs
    }

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
            this.currentMaxAgeMs = this.nextMaxAgeMs()
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
        if (!this.cachedValue || Date.now() - this.lastRefreshTime > this.currentMaxAgeMs) {
            void this.refresh().catch(this.errorHandler)
        }
    }
}
