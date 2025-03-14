/**
 * We have a common pattern across consumers where we want to:
 * - Load a value lazily
 * - Minimize queries to the DB for multiple values (e.g. teams for events)
 * - Keep that value cached ensuring any caller to retreive it will get the value
 * - "Refresh" the value after a certain age
 * - "Drop" the value after a much longer age
 */

const REFRESH_AGE = 1000 * 60 * 5 // 5 minutes
const DROP_AGE = 1000 * 60 * 60 * 24 // 24 hours

export class LazyLoader<T> {
    private cache: Record<string, T>
    private lastUsed: Record<string, number>

    constructor(
        private readonly options: {
            loader: () => Promise<T>
            refreshAge?: number
            dropAge?: number
        }
    ) {
        this.cache = {}
        this.lastUsed = {}
    }
}
