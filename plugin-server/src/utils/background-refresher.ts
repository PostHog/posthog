// A background refresher will:
// 1. Run a function on a schedule
// 2. Run the function immediately on startup
// 3. Provide a promise getter that returns the result of the function
// 4. Will only run a single instance of the function at a time
// 5. Will refresh the cached value at a given interval

export class BackgroundRefresher<T> {
    private cachedValue: T | null = null
    private cachedValuePromise: Promise<T> | null = null
    private lastRefreshTime = 0

    constructor(
        private readonly refreshFunction: () => Promise<T>,
        private readonly refreshOnStartup: boolean = true,
        private readonly maxAgeMs: number = 1000 * 60
    ) {}

    public async start(): Promise<void> {
        if (this.refreshOnStartup) {
            await this.refresh()
        }
    }

    public async refresh(): Promise<T> {
        if (this.cachedValuePromise) {
            return this.cachedValuePromise
        }

        this.cachedValuePromise = this.refreshFunction()
        this.cachedValue = await this.cachedValuePromise
        this.cachedValuePromise = null
        this.lastRefreshTime = Date.now()

        return this.cachedValue
    }

    public async get(): Promise<T> {
        if (!this.cachedValuePromise) {
            await this.refresh()
        }

        if (Date.now() - this.lastRefreshTime > this.maxAgeMs) {
            // We trigger the refresh but we don't use it
            void this.refresh()
        }

        return this.cachedValuePromise!
    }
}
