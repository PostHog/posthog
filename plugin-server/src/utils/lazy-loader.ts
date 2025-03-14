/**
 * We have a common pattern across consumers where we want to:
 * - Load a value lazily
 * - Minimize queries to the DB for multiple values (e.g. teams for events)
 * - Keep that value cached ensuring any caller to retreive it will get the value
 * - "Refresh" the value after a certain age
 * - "Drop" the value after a much longer age
 */
export class LazyLoader<T> {
    private loaded = false
    private value: T | undefined

    constructor(private readonly loader: () => Promise<T>) {}
}
