import type { Pool } from 'pg'

export const MIGRATIONS: readonly string[] = [
    `CREATE TABLE IF NOT EXISTS runs (
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
        series jsonb,
        topology jsonb,
        evidence_dir text,
        received_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )`,
    'CREATE INDEX IF NOT EXISTS runs_started_at ON runs (started_at DESC)',
    'CREATE INDEX IF NOT EXISTS runs_card_started_at ON runs (card_id, started_at DESC)',
]

const MIGRATION_LOCK = 0x5ce7a710

export async function migrate(pool: Pool): Promise<void> {
    const client = await pool.connect()
    try {
        await client.query('BEGIN')
        await client.query('SELECT pg_advisory_xact_lock($1)', [MIGRATION_LOCK])
        for (const statement of MIGRATIONS) {
            await client.query(statement)
        }
        await client.query('COMMIT')
    } catch (error) {
        await client.query('ROLLBACK')
        throw error
    } finally {
        client.release()
    }
}
