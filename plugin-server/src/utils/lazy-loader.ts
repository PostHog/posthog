const REFRESH_AGE = 1000 * 60 * 5 // 5 minutes

/**
 * We have a common pattern across consumers where we want to:
 * - Load a value lazily
 * - Minimize queries to the DB for multiple values (e.g. teams for events)
 * - Keep that value cached ensuring any caller to retrieve it will get the value
 * - "Refresh" the value after a certain age
 * - "Drop" the value after a much longer age
 */
export class LazyLoader<T> {
    private cache: Record<string, T | null | undefined>
    private lastUsed: Record<string, number | undefined>
    private lastRefreshed: Record<string, number | undefined>

    constructor(
        private readonly options: {
            loader: (key: string[]) => Promise<Record<string, T | undefined>>
            refreshAge?: number
            refreshNullAge?: number
            dropAge?: number
            throwOnLoadError?: boolean
        }
    ) {
        this.cache = {}
        this.lastUsed = {}
        this.lastRefreshed = {}
    }

    /**
     * Ensure that a range of values are preloaded and cached.
     *
     * If already cached, the lastUsed value is updated to now.
     * If not cached, the value is loaded as part of the batch and added to the cache.
     * If the value is older than the refreshAge, it is loaded from the database.
     */
    public async ensureLoaded(keys: string[]): Promise<Record<string, T | null>> {
        const results: Record<string, T | null> = {}

        const now = Date.now()
        const { loader, refreshAge = REFRESH_AGE, refreshNullAge = REFRESH_AGE } = this.options
        const keysToLoad = new Set<string>()

        // First, check if all keys are already cached and update the lastUsed time
        for (const key of keys) {
            const cached = this.cache[key]

            if (cached !== undefined) {
                results[key] = cached
                this.lastUsed[key] = now

                const lastRefreshed = this.lastRefreshed[key] ?? 0

                if (now - lastRefreshed > (cached === null ? refreshNullAge : refreshAge)) {
                    keysToLoad.add(key)
                }
            } else {
                keysToLoad.add(key)
            }
        }

        const loaded = await loader(Array.from(keysToLoad))
        for (const key of keysToLoad) {
            this.cache[key] = loaded[key] ?? null
            this.lastRefreshed[key] = now
            this.lastUsed[key] = now
        }

        return results
    }

    public async get(key: string): Promise<T | null | undefined> {
        const loaded = await this.ensureLoaded([key])
        return loaded[key]
    }

    public async getMany(keys: string[]): Promise<Record<string, T | null>> {
        return await this.ensureLoaded(keys)
    }

    public markForRefresh(key: string): void {
        delete this.lastRefreshed[key]
    }
}
