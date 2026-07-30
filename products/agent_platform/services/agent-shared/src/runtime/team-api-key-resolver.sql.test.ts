import { Pool, type PoolClient } from 'pg'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { SELECT_TEAM_API_TOKEN } from './team-api-key-resolver'

/**
 * The fake-pool unit test only asserts `resolve` passes `[teamId]`, not that the
 * query filters on it — drop `WHERE id = $1` and the resolver mints another
 * team's `phc_` bearer while unit tests stay green. This runs the real
 * `SELECT_TEAM_API_TOKEN` against Postgres with two teams to catch that.
 */
const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

const TEAM_ONE = 1
const TEAM_TWO = 2

describe('SELECT_TEAM_API_TOKEN team isolation (real SQL)', () => {
    let pool: Pool
    let client: PoolClient // one connection — temp tables are session-scoped

    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL, max: 1 })
        client = await pool.connect()
        // Temp table shadows real posthog_team for this session only — no schema
        // dependency, auto-dropped on disconnect.
        await client.query(`
            CREATE TEMP TABLE posthog_team (id int PRIMARY KEY, api_token text);
            INSERT INTO posthog_team (id, api_token) VALUES
                (${TEAM_ONE}, 'phc_team_one'),
                (${TEAM_TWO}, 'phc_team_two');
        `)
    })

    afterAll(async () => {
        client?.release()
        await pool?.end()
    })

    it("a team's lookup returns only its own api_token (never a sibling's)", async () => {
        const one = await client.query<{ api_token: string }>(SELECT_TEAM_API_TOKEN, [TEAM_ONE])
        const two = await client.query<{ api_token: string }>(SELECT_TEAM_API_TOKEN, [TEAM_TWO])
        expect(one.rows).toHaveLength(1)
        expect(one.rows[0].api_token).toBe('phc_team_one')
        expect(two.rows[0].api_token).toBe('phc_team_two')
    })

    it('a missing team returns zero rows (no fallback to a sibling)', async () => {
        const { rows } = await client.query(SELECT_TEAM_API_TOKEN, [999])
        expect(rows).toHaveLength(0)
    })
})
