/**
 * Test-harness reset helper for the v2 agent platform.
 *
 * Schema is owned by Django (the `agent_platform` product DB) — migrations live
 * in products/agent_platform/backend/migrations/ and are the single source of
 * truth. This module does NOT define or migrate schema: the test DB must already
 * be migrated before the suite runs (CI runs `migrate_product_databases`;
 * locally, `bin/migrate-agent-test-db` — see
 * products/agent_platform/docs/local-dev.md). `reset()` only truncates between
 * cases, so there is no hand-maintained DDL here to drift from the models.
 */

// `pg` is CommonJS; the named-import form breaks at boot under `tsx watch`
// ("does not provide an export named 'Pool'"). Destructure off the default
// import at runtime — same workaround as create-pool.ts.
import pg from 'pg'
const { Pool } = pg

export interface ResetOpts {
    databaseUrl?: string
}

/**
 * True if the (test) Postgres at `databaseUrl` accepts a one-shot connection.
 * Lets a real-PG suite skip itself when the local DB isn't wired, instead of
 * failing. Shared here so the probe isn't re-implemented per test file.
 */
export async function isReachable(databaseUrl: string): Promise<boolean> {
    const probe = new Pool({ connectionString: databaseUrl, max: 1 })
    try {
        await probe.query('SELECT 1')
        return true
    } catch {
        return false
    } finally {
        await probe.end().catch(() => undefined)
    }
}

/**
 * Truncate every `agent_*` table in the given (test) database so each case
 * starts clean. Tables are discovered dynamically rather than hardcoded, so a
 * new agent_platform migration is covered without touching this file. CASCADE
 * clears dependents and RESTART IDENTITY resets sequences; `django_migrations`
 * isn't an `agent_*` table, so the applied-migration state is preserved.
 *
 * Throws if no `agent_*` tables exist — that means the test DB hasn't been
 * migrated. Apply the agent_platform Django migrations first (CI:
 * `migrate_product_databases`; local: `bin/migrate-agent-test-db`).
 */
export async function reset(opts: ResetOpts = {}): Promise<void> {
    const databaseUrl = opts.databaseUrl ?? process.env.AGENT_DB_URL
    if (!databaseUrl) {
        throw new Error('test-reset: databaseUrl or AGENT_DB_URL is required')
    }
    const pool = new Pool({ connectionString: databaseUrl, max: 1 })
    try {
        const { rows } = await pool.query<{ tablename: string }>(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename ~ '^agent_'"
        )
        if (rows.length === 0) {
            throw new Error(
                `test-reset: no agent_* tables found in the test DB. It isn't migrated — ` +
                    'apply the agent_platform Django migrations first (CI: migrate_product_databases; ' +
                    'local: bin/migrate-agent-test-db). See products/agent_platform/docs/local-dev.md.'
            )
        }
        const tables = rows.map((r) => `"${r.tablename}"`).join(', ')
        await pool.query(`TRUNCATE ${tables} RESTART IDENTITY CASCADE`)
    } finally {
        await pool.end()
    }
}
