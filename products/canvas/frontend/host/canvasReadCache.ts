// Deterministic stringify for cache keys: object keys sort at every depth, so two reads
// that differ only by key order share an entry. `undefined` and non-finite numbers get
// their own tokens, because JSON.stringify collapses them all to `null`.
export function stableStringify(value: unknown): string {
    if (value === undefined) {
        return 'undef'
    }
    if (value === null) {
        return 'null'
    }
    if (typeof value === 'number') {
        return Number.isFinite(value) ? String(value) : `num:${String(value)}`
    }
    if (typeof value !== 'object') {
        return JSON.stringify(value)
    }
    if (Array.isArray(value)) {
        return `[${value.map(stableStringify).join(',')}]`
    }
    const entries = Object.entries(value as Record<string, unknown>)
        .filter(([, entry]) => entry !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`)
    return `{${entries.join(',')}}`
}

interface CacheEntry {
    value: unknown
    expiresAt: number
}

const MAX_ENTRIES = 256

/**
 * A small TTL cache for canvas reads. An iframe reboot or a render loop resolves a
 * repeated read from here instead of hitting ClickHouse again, and identical reads in
 * flight share one request.
 */
export class CanvasReadCache {
    private readonly entries = new Map<string, CacheEntry>()
    private readonly inFlight = new Map<string, Promise<unknown>>()

    constructor(private readonly now: () => number = Date.now) {}

    async read<T>(method: string, input: unknown, ttlSeconds: number, run: () => Promise<T>): Promise<T> {
        const key = `${method}:${stableStringify(input)}`
        const cached = this.entries.get(key)
        if (cached && cached.expiresAt > this.now()) {
            return cached.value as T
        }
        const pending = this.inFlight.get(key)
        if (pending) {
            return pending as Promise<T>
        }
        const request = run()
            .then((value) => {
                this.entries.delete(key)
                this.entries.set(key, { value, expiresAt: this.now() + ttlSeconds * 1_000 })
                if (this.entries.size > MAX_ENTRIES) {
                    const oldest = this.entries.keys().next().value
                    if (oldest !== undefined) {
                        this.entries.delete(oldest)
                    }
                }
                return value
            })
            .finally(() => this.inFlight.delete(key))
        this.inFlight.set(key, request)
        return request
    }
}
