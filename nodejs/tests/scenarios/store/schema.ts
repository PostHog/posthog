import type { Pool, PoolClient } from 'pg'

const SCHEMA_STATEMENTS: readonly string[] = [
    `CREATE TABLE IF NOT EXISTS runs (
        run_id uuid PRIMARY KEY,
        card_id text NOT NULL,
        status text NOT NULL,
        adapters text[] NOT NULL DEFAULT '{}',
        owners text[] NOT NULL DEFAULT '{}',
        target text,
        host text,
        head_sha text,
        card_hash text,
        started_at timestamptz NOT NULL,
        ended_at timestamptz NOT NULL,
        scorecard jsonb NOT NULL,
        series jsonb,
        topology jsonb,
        manifest jsonb,
        evidence_dir text,
        received_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )`,
    'CREATE INDEX IF NOT EXISTS runs_started_at ON runs (started_at DESC)',
    'CREATE INDEX IF NOT EXISTS runs_card_started_at ON runs (card_id, started_at DESC)',
    'CREATE INDEX IF NOT EXISTS runs_adapters ON runs USING gin (adapters)',
    'CREATE INDEX IF NOT EXISTS runs_owners ON runs USING gin (owners)',
]

const SCHEMA_LOCK = 0x5ce7a710

async function applyStatements(client: PoolClient): Promise<void> {
    await client.query('BEGIN')
    await client.query('SELECT pg_advisory_xact_lock($1)', [SCHEMA_LOCK])
    for (const statement of SCHEMA_STATEMENTS) {
        await client.query(statement)
    }
    await client.query('COMMIT')
}

export async function ensureSchema(pool: Pool): Promise<void> {
    const client = await pool.connect()
    try {
        await applyStatements(client)
        client.release()
    } catch (error) {
        await client.query('ROLLBACK').catch(() => undefined)
        client.release(error instanceof Error ? error : true)
        throw error
    }
}
