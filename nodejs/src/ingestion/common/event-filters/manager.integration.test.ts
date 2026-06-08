import { v4 } from 'uuid'

import { createOrganization, createTeam, insertRow, resetTestDatabase } from '../../../../tests/helpers/sql'
import { defaultConfig } from '../../../config/config'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { evaluateFilterTree } from './evaluate'
import { EventFilterManager } from './manager'
import { and, cond, not, or } from './test-helpers'

async function insertFilter(
    postgres: PostgresRouter,
    teamId: number,
    mode: string,
    filterTree: object | null,
    id?: string
) {
    await insertRow(postgres, 'posthog_eventfilterconfig', {
        id: id ?? v4(),
        team_id: teamId,
        mode,
        filter_tree: filterTree !== null ? JSON.stringify(filterTree) : null,
        test_cases: JSON.stringify([]),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
}

/**
 * Insert a raw row bypassing insertRow helper, allowing arbitrary column values
 * including malformed data that Django validation would normally reject.
 */
async function insertRawFilter(
    postgres: PostgresRouter,
    values: {
        id?: string
        team_id: number
        mode: string
        filter_tree: string | null
        test_cases?: string
    }
) {
    await postgres.query(
        PostgresUse.COMMON_WRITE,
        `INSERT INTO posthog_eventfilterconfig (id, team_id, mode, filter_tree, test_cases, created_at, updated_at)
         VALUES ($1, $2, $3, $4, $5, NOW(), NOW())`,
        [values.id ?? v4(), values.team_id, values.mode, values.filter_tree, values.test_cases ?? '[]'],
        'insert-raw-filter'
    )
}

describe('EventFilterManager integration', () => {
    let postgres: PostgresRouter
    let teamId: number
    let teamId2: number

    beforeEach(async () => {
        await resetTestDatabase()
        postgres = new PostgresRouter({ ...defaultConfig, POSTGRES_CONNECTION_POOL_SIZE: 1 })

        const orgId = await createOrganization(postgres)
        teamId = await createTeam(postgres, orgId)
        teamId2 = await createTeam(postgres, orgId)
    })

    afterEach(async () => {
        await postgres.end()
    })

    async function createManagerAndWaitForLoad(): Promise<EventFilterManager> {
        const manager = new EventFilterManager(postgres)
        // Wait for the background refresher to complete its initial load
        await new Promise((r) => setTimeout(r, 200))
        return manager
    }

    it('loads a live filter from postgres and evaluates it', async () => {
        await insertFilter(postgres, teamId, 'live', cond('event_name', 'exact', '$internal'))

        const manager = await createManagerAndWaitForLoad()
        const filter = manager.getFilter(teamId)

        expect(filter).not.toBeNull()
        expect(filter!.mode).toBe('live')
        expect(evaluateFilterTree(filter!.filter_tree, { event_name: '$internal' })).toBe(true)
        expect(evaluateFilterTree(filter!.filter_tree, { event_name: '$pageview' })).toBe(false)
    })

    it('loads a dry_run filter from postgres', async () => {
        await insertFilter(postgres, teamId, 'dry_run', cond('event_name', 'exact', '$test'))

        const manager = await createManagerAndWaitForLoad()
        const filter = manager.getFilter(teamId)

        expect(filter).not.toBeNull()
        expect(filter!.mode).toBe('dry_run')
    })

    it('does not load disabled filters', async () => {
        await insertFilter(postgres, teamId, 'disabled', cond('event_name', 'exact', 'pageview'))

        const manager = await createManagerAndWaitForLoad()

        expect(manager.getFilter(teamId)).toBeNull()
    })

    it('does not load filters with null filter_tree', async () => {
        await insertFilter(postgres, teamId, 'live', null)

        const manager = await createManagerAndWaitForLoad()

        expect(manager.getFilter(teamId)).toBeNull()
    })

    it('returns null for filter with empty tree (no conditions)', async () => {
        await insertFilter(postgres, teamId, 'live', { type: 'or', children: [] })

        const manager = await createManagerAndWaitForLoad()

        expect(manager.getFilter(teamId)).toBeNull()
    })

    it('returns null for unknown team', async () => {
        const manager = await createManagerAndWaitForLoad()

        expect(manager.getFilter(999999)).toBeNull()
    })

    it('loads filters for multiple teams', async () => {
        await insertFilter(postgres, teamId, 'live', cond('event_name', 'exact', 'a'))
        await insertFilter(postgres, teamId2, 'dry_run', cond('distinct_id', 'contains', 'bot'))

        const manager = await createManagerAndWaitForLoad()

        const f1 = manager.getFilter(teamId)
        const f2 = manager.getFilter(teamId2)

        expect(f1).not.toBeNull()
        expect(f2).not.toBeNull()
        expect(f1!.mode).toBe('live')
        expect(f2!.mode).toBe('dry_run')
    })

    it('skips rows with invalid filter_tree structure', async () => {
        await insertRawFilter(postgres, {
            team_id: teamId,
            mode: 'live',
            filter_tree: JSON.stringify({ type: 'invalid' }),
        })
        await insertFilter(postgres, teamId2, 'live', cond('event_name', 'exact', 'good'))

        const manager = await createManagerAndWaitForLoad()

        expect(manager.getFilter(teamId)).toBeNull()
        expect(manager.getFilter(teamId2)).not.toBeNull()
    })

    // These tests verify that corrupt or unexpected data in Postgres
    // (e.g. from Django bugs, manual SQL, migrations) never crashes ingestion.
    // Each bad row should be silently skipped without affecting other teams.
    describe('resilience to corrupt postgres data', () => {
        it('skips filter_tree that is a plain string instead of JSON object', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: '"just a string"',
            })
            await insertFilter(postgres, teamId2, 'live', cond('event_name', 'exact', 'good'))

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
            expect(manager.getFilter(teamId2)).not.toBeNull()
        })

        it('skips filter_tree that is a JSON array instead of object', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify([
                    { type: 'condition', field: 'event_name', operator: 'exact', value: 'x' },
                ]),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree that is a JSON number', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: '42',
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree with unknown node type', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({ type: 'xor', children: [] }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree with invalid field in condition', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({ type: 'condition', field: 'session_id', operator: 'exact', value: 'x' }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree with invalid operator in condition', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({ type: 'condition', field: 'event_name', operator: 'regex', value: 'x' }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree with empty value in condition', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({ type: 'condition', field: 'event_name', operator: 'exact', value: '' }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree with numeric value in condition', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({ type: 'condition', field: 'event_name', operator: 'exact', value: 123 }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree with missing children in AND node', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({ type: 'and' }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips filter_tree with missing child in NOT node', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({ type: 'not' }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips row with unknown mode value', async () => {
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'turbo',
                filter_tree: JSON.stringify(cond('event_name', 'exact', 'pageview')),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('skips deeply nested but structurally invalid tree', async () => {
            // Valid outer structure, but a leaf node is broken
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({
                    type: 'and',
                    children: [
                        { type: 'condition', field: 'event_name', operator: 'exact', value: 'good' },
                        { type: 'condition', field: 'event_name', operator: 'exact', value: 999 },
                    ],
                }),
            })

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('one bad row does not prevent loading other teams', async () => {
            // Team 1: broken
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: '"garbage"',
            })
            // Team 2: valid
            await insertFilter(postgres, teamId2, 'live', cond('event_name', 'exact', 'drop_me'))

            const manager = await createManagerAndWaitForLoad()

            expect(manager.getFilter(teamId)).toBeNull()
            const f2 = manager.getFilter(teamId2)
            expect(f2).not.toBeNull()
            expect(evaluateFilterTree(f2!.filter_tree, { event_name: 'drop_me' })).toBe(true)
        })

        it('extra unknown fields in filter_tree are tolerated', async () => {
            // Django might add new fields in the future — they should be ignored
            await insertRawFilter(postgres, {
                team_id: teamId,
                mode: 'live',
                filter_tree: JSON.stringify({
                    type: 'condition',
                    field: 'event_name',
                    operator: 'exact',
                    value: 'test',
                    description: 'some future field',
                    priority: 5,
                }),
            })

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)

            expect(filter).not.toBeNull()
            expect(evaluateFilterTree(filter!.filter_tree, { event_name: 'test' })).toBe(true)
        })
    })

    // treeHasConditions is called inside getFilter — trees with no real conditions
    // are treated as if the filter doesn't exist (returns null).
    describe('filters without real conditions return null', () => {
        it('empty AND group', async () => {
            await insertFilter(postgres, teamId, 'live', { type: 'and', children: [] })
            const manager = await createManagerAndWaitForLoad()
            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('empty OR group', async () => {
            await insertFilter(postgres, teamId, 'live', { type: 'or', children: [] })
            const manager = await createManagerAndWaitForLoad()
            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('NOT wrapping empty group', async () => {
            await insertFilter(postgres, teamId, 'live', not({ type: 'or', children: [] }))
            const manager = await createManagerAndWaitForLoad()
            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('nested empty groups', async () => {
            await insertFilter(postgres, teamId, 'live', {
                type: 'or',
                children: [{ type: 'and', children: [{ type: 'or', children: [] }] }],
            })
            const manager = await createManagerAndWaitForLoad()
            expect(manager.getFilter(teamId)).toBeNull()
        })

        it('single condition is not empty', async () => {
            await insertFilter(postgres, teamId, 'live', cond('event_name', 'exact', 'pageview'))
            const manager = await createManagerAndWaitForLoad()
            expect(manager.getFilter(teamId)).not.toBeNull()
        })

        it('nested condition is not empty', async () => {
            await insertFilter(postgres, teamId, 'live', and(cond('event_name', 'exact', 'pageview')))
            const manager = await createManagerAndWaitForLoad()
            expect(manager.getFilter(teamId)).not.toBeNull()
        })

        it('NOT wrapping condition is not empty', async () => {
            await insertFilter(postgres, teamId, 'live', not(cond('event_name', 'exact', 'pageview')))
            const manager = await createManagerAndWaitForLoad()
            expect(manager.getFilter(teamId)).not.toBeNull()
        })
    })

    describe('complex filter evaluation end-to-end', () => {
        it('AND with two conditions', async () => {
            const tree = and(cond('event_name', 'exact', 'pageview'), cond('distinct_id', 'exact', 'bot-1'))
            await insertFilter(postgres, teamId, 'live', tree)

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)!

            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'pageview', distinct_id: 'bot-1' })).toBe(true)
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'pageview', distinct_id: 'user' })).toBe(false)
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'click', distinct_id: 'bot-1' })).toBe(false)
        })

        it('OR with two conditions', async () => {
            const tree = or(cond('event_name', 'exact', 'pageview'), cond('event_name', 'exact', 'click'))
            await insertFilter(postgres, teamId, 'live', tree)

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)!

            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'pageview' })).toBe(true)
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'click' })).toBe(true)
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'submit' })).toBe(false)
        })

        it('NOT inverts condition', async () => {
            const tree = not(cond('event_name', 'exact', 'keep'))
            await insertFilter(postgres, teamId, 'live', tree)

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)!

            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'keep' })).toBe(false)
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'other' })).toBe(true)
        })

        it('contains operator', async () => {
            const tree = cond('distinct_id', 'contains', 'bot-')
            await insertFilter(postgres, teamId, 'live', tree)

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)!

            expect(evaluateFilterTree(filter.filter_tree, { distinct_id: 'bot-crawler' })).toBe(true)
            expect(evaluateFilterTree(filter.filter_tree, { distinct_id: 'real-user' })).toBe(false)
        })

        // Mirrors Python test_complex_tree_with_many_test_cases:
        // Drop if: (event is "$autocapture" OR event contains "bot_")
        //          AND NOT (distinct_id is "admin-user")
        it('AND + OR + NOT complex tree', async () => {
            const tree = and(
                or(cond('event_name', 'exact', '$autocapture'), cond('event_name', 'contains', 'bot_')),
                not(cond('distinct_id', 'exact', 'admin-user'))
            )
            await insertFilter(postgres, teamId, 'live', tree)

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)!

            // $autocapture from regular user -> drop
            expect(evaluateFilterTree(filter.filter_tree, { event_name: '$autocapture', distinct_id: 'user-1' })).toBe(
                true
            )
            // bot_ prefixed event from regular user -> drop
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'bot_heartbeat', distinct_id: 'user-2' })).toBe(
                true
            )
            // $autocapture from admin -> protected by NOT, ingest
            expect(
                evaluateFilterTree(filter.filter_tree, { event_name: '$autocapture', distinct_id: 'admin-user' })
            ).toBe(false)
            // bot_ event from admin -> also protected
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'bot_ping', distinct_id: 'admin-user' })).toBe(
                false
            )
            // normal event from regular user -> doesn't match OR, ingest
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'purchase', distinct_id: 'user-1' })).toBe(
                false
            )
            // normal event from admin -> ingest
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'login', distinct_id: 'admin-user' })).toBe(
                false
            )
            // partial match on "bot_" via contains -> drop
            expect(
                evaluateFilterTree(filter.filter_tree, { event_name: 'internal_bot_check', distinct_id: 'service-1' })
            ).toBe(true)
            // event_name missing -> OR returns false, ingest
            expect(evaluateFilterTree(filter.filter_tree, { distinct_id: 'user-1' })).toBe(false)
            // distinct_id missing -> NOT(false)=true, OR still needs to match
            expect(evaluateFilterTree(filter.filter_tree, { event_name: '$autocapture' })).toBe(true)
        })

        // Mirrors Python test_test_case_with_distinct_id
        it('AND with event_name and distinct_id', async () => {
            const tree = and(cond('event_name', 'exact', 'pageview'), cond('distinct_id', 'contains', 'bot'))
            await insertFilter(postgres, teamId, 'live', tree)

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)!

            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'pageview', distinct_id: 'bot-123' })).toBe(
                true
            )
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'pageview', distinct_id: 'user-1' })).toBe(
                false
            )
        })

        it('NOT wrapping OR (allowlist pattern)', async () => {
            const tree = not(or(cond('event_name', 'exact', 'allowed_1'), cond('event_name', 'exact', 'allowed_2')))
            await insertFilter(postgres, teamId, 'live', tree)

            const manager = await createManagerAndWaitForLoad()
            const filter = manager.getFilter(teamId)!

            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'allowed_1' })).toBe(false)
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'allowed_2' })).toBe(false)
            expect(evaluateFilterTree(filter.filter_tree, { event_name: 'other' })).toBe(true)
        })
    })
})
