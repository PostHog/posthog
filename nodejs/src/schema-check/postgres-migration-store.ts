import { Client, QueryResultRow } from 'pg'

import { AppliedMigration, MigrationStore, SqlxMigrationRow, SqlxMigrationStore } from './check'

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

// pg returns BIGINT as a string. sqlx versions are timestamps far below 2^53, so Number() keeps them exact.
const FETCH_SQLX_ROWS_SQL = `
    SELECT version::text AS version, success FROM _sqlx_migrations
    WHERE version = ANY($1::bigint[]) OR NOT success
`

// Opens a fresh connection per query so that a dropped connection during a long wait does not stick.
async function queryInTransaction<Row extends QueryResultRow>(
    options: PostgresMigrationStoreOptions,
    sql: string,
    params: unknown[]
): Promise<Row[]> {
    // The statement timeout must not go into the Client config. pg sends it as a startup parameter,
    // and PgBouncer drops connections with startup parameters it does not track.
    const client = new Client({
        connectionString: options.databaseUrl,
        connectionTimeoutMillis: options.connectTimeoutMs,
        query_timeout: options.statementTimeoutMs,
        application_name: 'node-schema-check',
    })
    // pg emits connection errors as events too. Without a listener they crash the process instead of the query.
    client.on('error', () => {})
    try {
        await client.connect()
        // SET LOCAL keeps the timeout inside this transaction, so PgBouncer in transaction mode
        // does not hand the setting to the next client of the server connection.
        await client.query('BEGIN')
        await client.query("SELECT set_config('statement_timeout', $1, true)", [String(options.statementTimeoutMs)])
        const result = await client.query<Row>(sql, params)
        await client.query('COMMIT')
        return result.rows
    } finally {
        await client.end().catch(() => {})
    }
}

export class PostgresMigrationStore implements MigrationStore {
    constructor(private readonly options: PostgresMigrationStoreOptions) {}

    fetchApplied(keys: AppliedMigration[]): Promise<AppliedMigration[]> {
        return queryInTransaction<AppliedMigration>(this.options, FETCH_APPLIED_SQL, [
            keys.map((key) => key.app),
            keys.map((key) => key.name),
        ])
    }

    async fetchLatestApplied(apps: string[]): Promise<Map<string, string>> {
        const rows = await queryInTransaction<AppliedMigration>(this.options, FETCH_LATEST_APPLIED_SQL, [apps])
        return new Map(rows.map((row) => [row.app, row.name]))
    }
}

export class PostgresSqlxMigrationStore implements SqlxMigrationStore {
    constructor(private readonly options: PostgresMigrationStoreOptions) {}

    async fetchRows(versions: number[]): Promise<SqlxMigrationRow[]> {
        const rows = await queryInTransaction<{ version: string; success: boolean }>(
            this.options,
            FETCH_SQLX_ROWS_SQL,
            [versions.map(String)]
        )
        return rows.map((row) => ({ version: Number(row.version), success: row.success }))
    }
}
