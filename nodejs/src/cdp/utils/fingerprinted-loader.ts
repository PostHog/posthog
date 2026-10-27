import { Counter } from 'prom-client'

const fingerprintedLoaderRows = new Counter({
    name: 'cdp_fingerprinted_loader_rows',
    help: 'Rows requested from a fingerprint-checked loader, by whether the full row was downloaded',
    labelNames: ['name', 'outcome'],
})

export const FINGERPRINT_COLUMN = '_fingerprint'

/**
 * A Postgres expression hashing the given columns. `updated_at` can't serve as a version: several
 * writers use queryset updates that leave it untouched (e.g. the hog flow email-sending pause).
 */
export const fingerprintSql = (fields: string[]): string => `md5(ROW(${fields.join(', ')})::text)`

export type FingerprintedLoaderOptions<T extends object> = {
    name: string
    peek: (id: string) => T | null | undefined
    fetchFingerprints: (ids: string[]) => Promise<Record<string, string>>
    fetchFull: (ids: string[]) => Promise<Record<string, { value: T; fingerprint: string }>>
}

/** A LazyLoader `loader` that re-downloads a cached row only when its fingerprint changed. */
export class FingerprintedLoader<T extends object> {
    // Keyed by the cached object, so entries go away when the LazyLoader evicts the value.
    private fingerprints = new WeakMap<T, string>()
    private forced = new Set<string>()

    constructor(private readonly options: FingerprintedLoaderOptions<T>) {}

    public forceFullReload(ids: string[]): void {
        for (const id of ids) {
            this.forced.add(id)
        }
    }

    public async load(ids: string[]): Promise<Record<string, T | undefined>> {
        const result: Record<string, T | undefined> = {}
        const toFetch: string[] = []
        const toCheck: { id: string; cached: T; fingerprint: string }[] = []
        const forced = ids.filter((id) => this.forced.has(id))

        for (const id of ids) {
            const cached = this.options.peek(id)
            const fingerprint = cached ? this.fingerprints.get(cached) : undefined
            if (!cached || !fingerprint || this.forced.has(id)) {
                toFetch.push(id)
            } else {
                toCheck.push({ id, cached, fingerprint })
            }
        }

        let unchanged = 0
        let removed = 0
        if (toCheck.length > 0) {
            const current = await this.options.fetchFingerprints(toCheck.map((x) => x.id))
            for (const { id, cached, fingerprint } of toCheck) {
                if (current[id] === undefined) {
                    removed++
                } else if (current[id] === fingerprint) {
                    result[id] = cached
                    unchanged++
                } else {
                    toFetch.push(id)
                }
            }
        }

        if (toFetch.length > 0) {
            const rows = await this.options.fetchFull(toFetch)
            for (const [id, { value, fingerprint }] of Object.entries(rows)) {
                this.fingerprints.set(value, fingerprint)
                result[id] = value
            }
        }

        // Cleared only once the load succeeded, so a retried load still does the full fetch.
        for (const id of forced) {
            this.forced.delete(id)
        }

        const metric = fingerprintedLoaderRows
        metric.labels({ name: this.options.name, outcome: 'unchanged' }).inc(unchanged)
        metric.labels({ name: this.options.name, outcome: 'removed' }).inc(removed)
        metric.labels({ name: this.options.name, outcome: 'fetched' }).inc(toFetch.length)

        return result
    }
}

export const splitFingerprint = <T extends object>(
    row: T & { [FINGERPRINT_COLUMN]: string }
): { value: T; fingerprint: string } => {
    const { [FINGERPRINT_COLUMN]: fingerprint, ...value } = row
    return { value: value as unknown as T, fingerprint }
}
