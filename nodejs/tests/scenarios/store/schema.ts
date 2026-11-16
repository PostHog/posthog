import type { Pool } from 'pg'

// Each entry runs once, in order, and never changes after it ships: the old app revision keeps
// serving while the new one migrates, so a new entry only adds.
export const MIGRATIONS: readonly string[] = [
    `CREATE TABLE runs (
        run_id uuid PRIMARY KEY,
        card_id text NOT NULL,
        status text NOT NULL,
        target text,
        host text,
        head_sha text,
        card_hash text,
        started_at timestamptz NOT NULL,
        ended_at timestamptz NOT NULL,
        scorecard jsonb NOT NULL,
        series bytea,
        topology jsonb,
        evidence_prefix text,
        received_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )`,
    'CREATE INDEX runs_started_at ON runs (started_at DESC)',
    'CREATE INDEX runs_card_started_at ON runs (card_id, started_at DESC)',
]

const MIGRATION_LOCK = 0x5ce7a710

export async function migrate(pool: Pool): Promise<void> {
    const client = await pool.connect()
    try {
        await client.query('BEGIN')
        // Two instances starting at once would both see an empty ledger without it.
        await client.query('SELECT pg_advisory_xact_lock($1)', [MIGRATION_LOCK])
        await client.query(
            'CREATE TABLE IF NOT EXISTS store_migrations (id integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())'
        )
        const { rows } = await client.query<{ id: number }>('SELECT id FROM store_migrations')
        const applied = new Set(rows.map(({ id }) => id))
        for (const [id, sql] of MIGRATIONS.entries()) {
            if (!applied.has(id)) {
                await client.query(sql)
                await client.query('INSERT INTO store_migrations (id) VALUES ($1)', [id])
            }
        }
        await client.query('COMMIT')
    } catch (error) {
        await client.query('ROLLBACK')
        throw error
    } finally {
        client.release()
    }
}
