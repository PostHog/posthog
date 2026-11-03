import { Client } from 'pg'

import { AppliedMigration, MigrationStore } from './check'

export interface PostgresMigrationStoreOptions {
    databaseUrl: string
    connectTimeoutMs: number
    statementTimeoutMs: number
}

const FETCH_APPLIED_SQL = `
    SELECT app, name FROM django_migrations
    WHERE (app, name) IN (SELECT * FROM unnest($1::text[], $2::text[]))
`

const FETCH_LATEST_APPLIED_SQL = `
    SELECT app, max(name) AS name FROM django_migrations
    WHERE app = ANY($1::text[])
    GROUP BY app
`

// Opens a fresh connection per query so that a dropped connection during a long wait does not stick.
export class PostgresMigrationStore implements MigrationStore {
    constructor(private readonly options: PostgresMigrationStoreOptions) {}

    private async query(sql: string, params: unknown[]): Promise<AppliedMigration[]> {
        // The statement timeout must not go into the Client config. pg sends it as a startup parameter,
        // and PgBouncer drops connections with startup parameters it does not track.
        const client = new Client({
            connectionString: this.options.databaseUrl,
            connectionTimeoutMillis: this.options.connectTimeoutMs,
            query_timeout: this.options.statementTimeoutMs,
            application_name: 'node-schema-check',
        })
        // pg emits connection errors as events too. Without a listener they crash the process instead of the query.
        client.on('error', () => {})
        try {
            await client.connect()
            // SET LOCAL keeps the timeout inside this transaction, so PgBouncer in transaction mode
            // does not hand the setting to the next client of the server connection.
            await client.query('BEGIN')
            await client.query("SELECT set_config('statement_timeout', $1, true)", [
                String(this.options.statementTimeoutMs),
            ])
            const result = await client.query<AppliedMigration>(sql, params)
            await client.query('COMMIT')
            return result.rows
        } finally {
            await client.end().catch(() => {})
        }
    }

    fetchApplied(keys: AppliedMigration[]): Promise<AppliedMigration[]> {
        return this.query(FETCH_APPLIED_SQL, [keys.map((key) => key.app), keys.map((key) => key.name)])
    }

    async fetchLatestApplied(apps: string[]): Promise<Map<string, string>> {
        const rows = await this.query(FETCH_LATEST_APPLIED_SQL, [apps])
        return new Map(rows.map((row) => [row.app, row.name]))
    }
}
