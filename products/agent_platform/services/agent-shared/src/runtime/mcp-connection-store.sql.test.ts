import { Pool, type PoolClient } from 'pg'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { SELECT_INSTALLATION } from './mcp-connection-store'

/**
 * The fake-pool unit test only asserts `resolve` passes the owner param, not that
 * the query filters on it — drop `AND i.user_id` and the IDOR reopens while unit
 * tests stay green. This runs the real `SELECT_INSTALLATION` against Postgres
 * with two owners to catch that.
 */
const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

const TEAM = 1
const OWNER_A = 100
const OWNER_B = 200

describe('SELECT_INSTALLATION owner isolation (real SQL)', () => {
    let pool: Pool
    let client: PoolClient // one connection — temp tables are session-scoped

    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL, max: 1 })
        client = await pool.connect()
        // Temp tables shadow the real mcp_store_* tables for this session only —
        // no schema/migration dependency, auto-dropped on disconnect.
        await client.query(`
            CREATE TEMP TABLE mcp_store_mcpservertemplate (
                id text PRIMARY KEY, oauth_metadata jsonb, oauth_credentials jsonb
            );
            CREATE TEMP TABLE mcp_store_mcpserverinstallation (
                id text PRIMARY KEY, team_id int, user_id int, url text, auth_type text,
                is_enabled boolean, sensitive_configuration jsonb, oauth_metadata jsonb, template_id text
            );
            INSERT INTO mcp_store_mcpserverinstallation
                (id, team_id, user_id, url, auth_type, is_enabled, sensitive_configuration, oauth_metadata, template_id)
            VALUES
                ('inst-a', ${TEAM}, ${OWNER_A}, 'https://a.test/mcp', 'api_key', true, '{}'::jsonb, '{}'::jsonb, NULL),
                ('inst-b', ${TEAM}, ${OWNER_B}, 'https://b.test/mcp', 'api_key', true, '{}'::jsonb, '{}'::jsonb, NULL);
        `)
    })

    afterAll(async () => {
        client?.release()
        await pool?.end()
    })

    it("owner A's lookup cannot return owner B's installation (the IDOR)", async () => {
        const { rows } = await client.query(SELECT_INSTALLATION, ['inst-b', TEAM, OWNER_A])
        expect(rows).toHaveLength(0)
    })

    it('the owner can fetch their own installation', async () => {
        const bAsB = await client.query(SELECT_INSTALLATION, ['inst-b', TEAM, OWNER_B])
        const aAsA = await client.query(SELECT_INSTALLATION, ['inst-a', TEAM, OWNER_A])
        expect(bAsB.rows).toHaveLength(1)
        expect(aAsA.rows).toHaveLength(1)
    })
})
