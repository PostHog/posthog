import { Pool } from 'pg'

/**
 * A Postgres pool that opens on the first `get()` and stays closed after `end()`. A process without a
 * connection string gets no pool, so its caller decides how to drop the work instead of throwing.
 */
export class LazyPool {
    private pool: Pool | null = null
    private ended = false

    constructor(
        private readonly databaseUrl: string | undefined,
        private readonly maxConnections: number | undefined,
        private readonly onError: (err: Error) => void
    ) {}

    // Built on first use, not in the constructor. Every CDP service set constructs the services that own
    // these pools, but only some of them use one. An eager pool would have every consumer, and every test
    // that builds a service set, holding connections it never uses.
    public get(): Pool | null {
        if (this.pool || this.ended || !this.databaseUrl) {
            return this.pool
        }
        this.pool = new Pool({ connectionString: this.databaseUrl, max: this.maxConnections })
        // pg throws an uncaught exception if an idle client errors with no listener attached, which
        // would take down the process for work its owner is allowed to drop.
        this.pool.on('error', this.onError)
        return this.pool
    }

    // Idempotent, because pg rejects a second end() with "Called end on pool more than once". A `get()`
    // during `drain` opens no new pool, but returns a pool that is already open.
    public async end(drain?: () => Promise<unknown>): Promise<void> {
        this.ended = true
        await drain?.()
        const pool = this.pool
        this.pool = null
        await pool?.end()
    }
}
