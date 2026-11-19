import { Pool } from 'pg'

import { UUIDT } from '~/common/utils/utils'

import { ConversionWatcherRow, CyclotronJobInvocationResult } from '../../types'
import { ConversionWatchersService } from './conversion-watchers.service'

const CYCLOTRON_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

const watcher = (functionId: string, goal: ConversionWatcherRow['goal'], expiresAt: Date): ConversionWatcherRow => {
    const id = new UUIDT().toString()
    return {
        id,
        team_id: 2,
        function_id: functionId,
        run_id: id,
        parent_run_id: null,
        distinct_id: `person-${id}`,
        person_id: null,
        flow_version: 1,
        goal,
        created_at: new Date(),
        expires_at: expiresAt,
    }
}

const results = (watchers: ConversionWatcherRow[]): CyclotronJobInvocationResult[] =>
    [{ conversionWatchers: watchers }] as unknown as CyclotronJobInvocationResult[]

describe('ConversionWatchersService', () => {
    let pool: Pool
    let service: ConversionWatchersService
    const functionId = new UUIDT().toString()

    beforeAll(() => {
        pool = new Pool({ connectionString: CYCLOTRON_DATABASE_URL })
    })

    beforeEach(() => {
        service = new ConversionWatchersService(CYCLOTRON_DATABASE_URL)
    })

    afterEach(async () => {
        await service.stop()
        await pool.query('DELETE FROM conversion_watchers WHERE function_id = $1', [functionId])
        await pool.query('DELETE FROM conversion_watcher_goals WHERE function_id = $1', [functionId])
    })

    afterAll(async () => {
        await pool.end()
    })

    it('records each distinct goal once, keeping the latest expiry of the watchers that hold it', async () => {
        const goalA = { events: [['_H', 1, 32, 'signed_up', 32, 'event', 1, 1, 11]] }
        const goalB = { properties: ['_H', 1, 32, 'plan', 32, 'properties', 32, 'person', 1, 3, 12] }
        const day = 24 * 60 * 60 * 1000
        const soon = new Date(Date.now() + day)
        const later = new Date(Date.now() + 3 * day)

        service.queueInvocationResults(
            results([
                watcher(functionId, goalA, soon),
                watcher(functionId, goalA, later),
                watcher(functionId, goalB, soon),
            ])
        )
        await service.flush()
        // A later watcher with an earlier expiry must not shorten the row.
        service.queueInvocationResults(results([watcher(functionId, goalA, soon)]))
        await service.flush()

        const goals = await pool.query(
            `SELECT g.goal, g.expires_at, g.goal_hash = md5(w.goal::text) AS hash_matches_watcher
             FROM conversion_watcher_goals g
             JOIN LATERAL (SELECT goal FROM conversion_watchers w WHERE w.function_id = g.function_id AND w.goal = g.goal LIMIT 1) w ON TRUE
             WHERE g.function_id = $1
             ORDER BY g.expires_at`,
            [functionId]
        )
        expect(goals.rows).toEqual([
            { goal: goalB, expires_at: soon.toISOString(), hash_matches_watcher: true },
            { goal: goalA, expires_at: later.toISOString(), hash_matches_watcher: true },
        ])
        const watchers = await pool.query('SELECT count(*)::int AS n FROM conversion_watchers WHERE function_id = $1', [
            functionId,
        ])
        expect(watchers.rows[0].n).toBe(4)
    })
})
