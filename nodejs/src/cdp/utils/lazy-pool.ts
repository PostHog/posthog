import { Pool } from 'pg'

export class LazyPool {
    private pool: Pool | null = null
    private ended = false

    constructor(
        private readonly databaseUrl: string | undefined,
        private readonly maxConnections: number | undefined,
        private readonly onError: (err: Error) => void
    ) {}

    public get(): Pool | null {
        if (this.pool || this.ended || !this.databaseUrl) {
            return this.pool
        }
        this.pool = new Pool({ connectionString: this.databaseUrl, max: this.maxConnections })
        this.pool.on('error', this.onError)
        return this.pool
    }

    public async end(drain?: () => Promise<unknown>): Promise<void> {
        this.ended = true
        await drain?.()
        const pool = this.pool
        this.pool = null
        await pool?.end()
    }
}
