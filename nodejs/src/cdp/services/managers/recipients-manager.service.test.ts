import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { createTeam, createTestTeamFixture, getTeam } from '~/tests/helpers/sql'
import { INVALID_TEAM_ID_KEYS } from '~/tests/helpers/team'
import { Hub, Team } from '~/types'

import { RecipientGetArgs, RecipientsManagerService } from './recipients-manager.service'

describe('RecipientsManager', () => {
    let hub: Hub
    let manager: RecipientsManagerService
    let team: Team
    let team2: Team

    beforeEach(async () => {
        hub = await createHub()
        manager = new RecipientsManagerService(hub.postgres)
        const { organizationId, team: fixtureTeam } = await createTestTeamFixture(hub.postgres)
        team = fixtureTeam
        const team2Id = await createTeam(hub.postgres, organizationId)
        team2 = (await getTeam(hub.postgres, team2Id))!
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const createRecipient = async (teamId: number, identifier: string, preferences: Record<string, string> = {}) => {
        const id = new UUIDT().toString()
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
             VALUES ($1, $2, $3, $4, NOW(), NOW(), false)`,
            [id, teamId, identifier, JSON.stringify(preferences)],
            'testInsertRecipient'
        )
        return id
    }

    describe('get', () => {
        it('should return null when recipient does not exist', async () => {
            const args: RecipientGetArgs = { teamId: team.id, identifier: 'nonexistent@example.com' }
            const result = await manager.get(args)
            expect(result).toBeNull()
        })

        it('should return recipient when it exists', async () => {
            const preferences = { 'category-1': 'OPTED_IN', 'category-2': 'OPTED_OUT' }
            const id = await createRecipient(team.id, 'user@example.com', preferences)

            const args: RecipientGetArgs = { teamId: team.id, identifier: 'user@example.com' }
            const result = await manager.get(args)

            expect(result).toEqual({
                id: id,
                team_id: team.id,
                identifier: 'user@example.com',
                preferences: preferences,
                created_at: expect.any(String),
                updated_at: expect.any(String),
            })
        })

        it('should handle invalid preference statuses by defaulting to NO_PREFERENCE', async () => {
            const preferences = { 'category-1': 'INVALID_STATUS', 'category-2': 'OPTED_IN' }
            await createRecipient(team.id, 'user@example.com', preferences)

            const args: RecipientGetArgs = { teamId: team.id, identifier: 'user@example.com' }
            const result = await manager.get(args)

            expect(result?.preferences).toEqual({
                'category-1': 'NO_PREFERENCE',
                'category-2': 'OPTED_IN',
            })
        })

        it('finds an email address stored in another case', async () => {
            await createRecipient(team.id, 'User@Example.com', { $all: 'OPTED_OUT' })

            const results = await manager.getMany([
                { teamId: team.id, identifier: 'user@example.com', anyCase: true },
                { teamId: team.id, identifier: 'USER@EXAMPLE.COM', anyCase: true },
            ])

            expect(results[`${team.id}:user@example.com`]?.preferences).toEqual({ $all: 'OPTED_OUT' })
            expect(results[`${team.id}:USER@EXAMPLE.COM`]?.preferences).toEqual({ $all: 'OPTED_OUT' })
        })

        it('lets the spelling the send names win over another spelling of the address', async () => {
            await createRecipient(team.id, 'user@example.com', { $all: 'OPTED_IN', 'category-1': 'OPTED_OUT' })
            await createRecipient(team.id, 'User@Example.com', { $all: 'OPTED_OUT' })

            const result = await manager.get({ teamId: team.id, identifier: 'user@example.com', anyCase: true })

            expect(result?.identifier).toBe('user@example.com')
            expect(result?.preferences).toEqual({ $all: 'OPTED_IN', 'category-1': 'OPTED_OUT' })
        })

        it('matches an identifier exactly unless the caller says it is an email address', async () => {
            await createRecipient(team.id, 'User@Example.com', { $all: 'OPTED_OUT' })

            expect(await manager.get({ teamId: team.id, identifier: 'user@example.com' })).toBeNull()
            expect(await manager.get({ teamId: team.id, identifier: 'user@example.com', anyCase: true })).not.toBeNull()
        })

        it('reads many spellings of one address without slowing down', async () => {
            // Every upper and lower case mix of 16 letters, 50,000 spellings of one address in all.
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
                 SELECT gen_random_uuid(), $1,
                    (SELECT string_agg(CASE WHEN (g >> i) & 1 = 1 THEN 'A' ELSE 'a' END, '' ORDER BY i) FROM generate_series(0, 15) i)
                        || '@example.com',
                    '{"$all": "OPTED_OUT"}', NOW(), NOW(), false
                 FROM generate_series(0, 49999) g`,
                [team.id],
                'testInsertSpellings'
            )

            const started = Date.now()
            const result = await manager.get({
                teamId: team.id,
                identifier: 'aaaaaaaaaaaaaaaa@example.com',
                anyCase: true,
            })

            expect(result?.preferences).toEqual({ $all: 'OPTED_OUT' })
            expect(Date.now() - started).toBeLessThan(2000)
        })

        it('should filter out deleted recipients', async () => {
            const id = await createRecipient(team.id, 'user@example.com', {})

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_messagerecipientpreference SET deleted = true WHERE id = $1`,
                [id],
                'testMarkDeleted'
            )

            const args: RecipientGetArgs = { teamId: team.id, identifier: 'user@example.com' }
            const result = await manager.get(args)
            expect(result).toBeNull()
        })
    })

    describe('getMany', () => {
        it('should return multiple recipients', async () => {
            const id1 = await createRecipient(team.id, 'user1@example.com', { 'cat-1': 'OPTED_IN' })
            const id2 = await createRecipient(team.id, 'user2@example.com', { 'cat-1': 'OPTED_OUT' })
            const id3 = await createRecipient(team2.id, 'user3@example.com', { 'cat-1': 'NO_PREFERENCE' })

            const args: RecipientGetArgs[] = [
                { teamId: team.id, identifier: 'user1@example.com' },
                { teamId: team.id, identifier: 'user2@example.com' },
                { teamId: team2.id, identifier: 'user3@example.com' },
                { teamId: team.id, identifier: 'nonexistent@example.com' }, // This should return null
            ]

            const results = await manager.getMany(args)

            expect(results[`${team.id}:user1@example.com`]).toEqual({
                id: id1,
                team_id: team.id,
                identifier: 'user1@example.com',
                preferences: { 'cat-1': 'OPTED_IN' },
                created_at: expect.any(String),
                updated_at: expect.any(String),
            })

            expect(results[`${team.id}:user2@example.com`]).toEqual({
                id: id2,
                team_id: team.id,
                identifier: 'user2@example.com',
                preferences: { 'cat-1': 'OPTED_OUT' },
                created_at: expect.any(String),
                updated_at: expect.any(String),
            })

            expect(results[`${team2.id}:user3@example.com`]).toEqual({
                id: id3,
                team_id: team2.id,
                identifier: 'user3@example.com',
                preferences: { 'cat-1': 'NO_PREFERENCE' },
                created_at: expect.any(String),
                updated_at: expect.any(String),
            })

            expect(results[`${team.id}:nonexistent@example.com`]).toBeNull()
        })

        it('should handle empty input', async () => {
            const results = await manager.getMany([])
            expect(results).toEqual({})
        })

        it.each(INVALID_TEAM_ID_KEYS)(
            'returns null for invalid team id %p without failing the valid team in the same load',
            async (key) => {
                await createRecipient(team.id, 'user1@example.com', { 'cat-1': 'OPTED_IN' })
                const invalidTeamId = key as unknown as number

                const results = await manager.getMany([
                    { teamId: team.id, identifier: 'user1@example.com' },
                    { teamId: invalidTeamId, identifier: 'user1@example.com' },
                ])

                expect(results[`${team.id}:user1@example.com`]?.preferences).toEqual({ 'cat-1': 'OPTED_IN' })
                expect(results[`${key}:user1@example.com`]).toBeNull()
                // A load that holds only invalid ids has no query to run.
                expect(await manager.get({ teamId: invalidTeamId, identifier: 'user2@example.com' })).toBeNull()
            }
        )
    })

    describe('getPreference', () => {
        it('should return the correct preference status', () => {
            const recipient = {
                id: 'test-id',
                team_id: team.id,
                identifier: 'user@example.com',
                preferences: {
                    'category-1': 'OPTED_IN' as const,
                    'category-2': 'OPTED_OUT' as const,
                },
                created_at: '2023-01-01T00:00:00Z',
                updated_at: '2023-01-01T00:00:00Z',
            }

            expect(manager.getPreference(recipient, 'category-1')).toBe('OPTED_IN')
            expect(manager.getPreference(recipient, 'category-2')).toBe('OPTED_OUT')
            expect(manager.getPreference(recipient, 'category-3')).toBe('NO_PREFERENCE')
        })
    })

    describe('optOut', () => {
        it('should create a new recipient with $all OPTED_OUT when none exists', async () => {
            await manager.optOut(team.id, ['new@example.com'])

            const result = await manager.get({ teamId: team.id, identifier: 'new@example.com' })
            expect(result).toMatchObject({
                team_id: team.id,
                identifier: 'new@example.com',
                preferences: { $all: 'OPTED_OUT' },
            })
        })

        it('should merge $all OPTED_OUT into existing preferences', async () => {
            await createRecipient(team.id, 'user@example.com', { 'category-1': 'OPTED_IN' })

            await manager.optOut(team.id, ['user@example.com'])

            const result = await manager.get({ teamId: team.id, identifier: 'user@example.com' })
            expect(result?.preferences).toEqual({
                'category-1': 'OPTED_IN',
                $all: 'OPTED_OUT',
            })
        })

        it('should overwrite existing $all preference with OPTED_OUT', async () => {
            await createRecipient(team.id, 'user@example.com', { $all: 'OPTED_IN', 'category-1': 'OPTED_IN' })

            await manager.optOut(team.id, ['user@example.com'])

            const result = await manager.get({ teamId: team.id, identifier: 'user@example.com' })
            expect(result?.preferences).toEqual({
                'category-1': 'OPTED_IN',
                $all: 'OPTED_OUT',
            })
        })

        it('should opt out multiple recipients in a single call', async () => {
            await createRecipient(team.id, 'user1@example.com', { 'category-1': 'OPTED_IN' })
            // user2 does not exist yet
            await createRecipient(team.id, 'user3@example.com', { 'category-1': 'OPTED_IN', 'category-2': 'OPTED_IN' })

            await manager.optOut(team.id, ['user1@example.com', 'user2@example.com', 'user3@example.com'])

            const result1 = await manager.get({ teamId: team.id, identifier: 'user1@example.com' })
            expect(result1?.preferences).toEqual({ 'category-1': 'OPTED_IN', $all: 'OPTED_OUT' })

            const result2 = await manager.get({ teamId: team.id, identifier: 'user2@example.com' })
            expect(result2?.preferences).toEqual({ $all: 'OPTED_OUT' })

            const result3 = await manager.get({ teamId: team.id, identifier: 'user3@example.com' })
            expect(result3?.preferences).toEqual({
                'category-1': 'OPTED_IN',
                'category-2': 'OPTED_IN',
                $all: 'OPTED_OUT',
            })
        })

        it('should be a no-op for an empty array', async () => {
            await createRecipient(team.id, 'user@example.com', { 'category-1': 'OPTED_IN' })

            await manager.optOut(team.id, [])

            const result = await manager.get({ teamId: team.id, identifier: 'user@example.com' })
            expect(result?.preferences).toEqual({ 'category-1': 'OPTED_IN' })
        })

        it('should clear the cache after opt-out', async () => {
            await createRecipient(team.id, 'user@example.com', { $all: 'OPTED_IN' })

            // Load into cache
            const before = await manager.get({ teamId: team.id, identifier: 'user@example.com' })
            expect(before?.preferences.$all).toBe('OPTED_IN')

            // Opt out (should clear cache)
            await manager.optOut(team.id, ['user@example.com'])

            // Should reflect the new value, not the cached one
            const after = await manager.get({ teamId: team.id, identifier: 'user@example.com' })
            expect(after?.preferences.$all).toBe('OPTED_OUT')
        })
    })

    describe('caching', () => {
        it('should cache results and not hit database on second call', async () => {
            const id = await createRecipient(team.id, 'user@example.com', { 'cat-1': 'OPTED_IN' })
            const args: RecipientGetArgs = { teamId: team.id, identifier: 'user@example.com' }

            const result1 = await manager.get(args)
            expect(result1?.id).toBe(id)

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_messagerecipientpreference WHERE id = $1`,
                [id],
                'testDeleteRecipient'
            )

            const result2 = await manager.get(args)
            expect(result2?.id).toBe(id)
        })

        it('should clear cache', async () => {
            const id = await createRecipient(team.id, 'user@example.com', { 'cat-1': 'OPTED_IN' })
            const args: RecipientGetArgs = { teamId: team.id, identifier: 'user@example.com' }

            await manager.get(args)

            manager.clear()

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_messagerecipientpreference WHERE id = $1`,
                [id],
                'testDeleteRecipient'
            )

            const result = await manager.get(args)
            expect(result).toBeNull()
        })
    })

    describe('getFresh', () => {
        it('excludes soft-deleted rows for earlier recipients in a multi-recipient batch', async () => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
                 VALUES ($1, $2, $3, $4, NOW(), NOW(), true)`,
                [new UUIDT().toString(), team.id, 'deleted@example.com', JSON.stringify({ 'cat-1': 'OPTED_OUT' })],
                'testInsertDeletedRecipient'
            )
            await createRecipient(team.id, 'live@example.com', { 'cat-1': 'OPTED_IN' })

            const [deletedFresh, liveFresh] = await Promise.all([
                manager.getFresh({ teamId: team.id, identifier: 'deleted@example.com', anyCase: true }),
                manager.getFresh({ teamId: team.id, identifier: 'live@example.com', anyCase: true }),
            ])
            expect(deletedFresh).toBeNull()
            expect(liveFresh?.preferences).toEqual({ 'cat-1': 'OPTED_IN' })

            const many = await manager.getMany([
                { teamId: team.id, identifier: 'deleted@example.com', anyCase: true },
                { teamId: team.id, identifier: 'live@example.com', anyCase: true },
            ])
            expect(many[`${team.id}:deleted@example.com`]).toBeNull()
            expect(many[`${team.id}:live@example.com`]?.preferences).toEqual({ 'cat-1': 'OPTED_IN' })
        })

        it('reads fresh primary state instead of a lagging replica and batches concurrent reads', async () => {
            const primarySchema = `fresh_primary_${team.id}`
            const replicaSchema = `fresh_replica_${team.id}`
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `CREATE SCHEMA ${primarySchema};
                 CREATE TABLE ${primarySchema}.posthog_messagerecipientpreference (LIKE public.posthog_messagerecipientpreference INCLUDING ALL);
                 CREATE SCHEMA ${replicaSchema};
                 CREATE TABLE ${replicaSchema}.posthog_messagerecipientpreference (LIKE public.posthog_messagerecipientpreference INCLUDING ALL);`,
                [],
                'testCreatePrimaryAndReplicaSchemas'
            )

            const primaryUrl = new URL(hub.DATABASE_URL)
            primaryUrl.searchParams.set('options', `-c search_path=${primarySchema},public`)
            const replicaUrl = new URL(hub.DATABASE_URL)
            replicaUrl.searchParams.set('options', `-c search_path=${replicaSchema},public`)
            const splitRouter = new PostgresRouter({
                ...hub,
                DATABASE_URL: primaryUrl.toString(),
                DATABASE_READONLY_URL: replicaUrl.toString(),
                POSTGRES_CONNECTION_POOL_SIZE: 1,
            })

            const readPrimaryScans = async (): Promise<number> => {
                await splitRouter.query(
                    PostgresUse.COMMON_WRITE,
                    'SELECT pg_stat_force_next_flush()',
                    [],
                    'testFlushStats'
                )
                await splitRouter.query(
                    PostgresUse.COMMON_WRITE,
                    'SELECT pg_stat_clear_snapshot()',
                    [],
                    'testClearSnapshot'
                )
                const { rows } = await splitRouter.query<{ scans: string }>(
                    PostgresUse.COMMON_WRITE,
                    `SELECT coalesce(seq_scan, 0) + coalesce(idx_scan, 0) AS scans
                     FROM pg_stat_user_tables
                     WHERE schemaname = $1 AND relname = 'posthog_messagerecipientpreference'`,
                    [primarySchema],
                    'testReadPrimaryScans'
                )
                return Number(rows[0]?.scans ?? 0)
            }

            try {
                const seededRecipients = Array.from({ length: 12 }, (_, index) => ({
                    stored: index === 0 ? 'Alice@Example.com' : `recipient-${index}@example.com`,
                    lookup: index === 0 ? 'alice@example.com' : `recipient-${index}@example.com`,
                    primaryStatus: index % 2 === 0 ? 'OPTED_OUT' : 'OPTED_IN',
                }))
                const primaryValues: unknown[] = [team.id]
                const primaryPlaceholders = seededRecipients
                    .map((recipient, index) => {
                        const idParam = index * 3 + 2
                        const identifierParam = index * 3 + 3
                        const prefsParam = index * 3 + 4
                        primaryValues.push(
                            new UUIDT().toString(),
                            recipient.stored,
                            JSON.stringify({ 'cat-1': recipient.primaryStatus })
                        )
                        return `($${idParam}, $1, $${identifierParam}, $${prefsParam}, NOW(), NOW(), false)`
                    })
                    .join(', ')
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO ${primarySchema}.posthog_messagerecipientpreference
                        (id, team_id, identifier, preferences, created_at, updated_at, deleted)
                     VALUES ${primaryPlaceholders}`,
                    primaryValues,
                    'testSeedPrimary'
                )
                const replicaValues: unknown[] = [team.id, JSON.stringify({ 'cat-1': 'OPTED_IN' })]
                const replicaPlaceholders = seededRecipients
                    .map((recipient, index) => {
                        const idParam = index * 2 + 3
                        const identifierParam = index * 2 + 4
                        replicaValues.push(new UUIDT().toString(), recipient.stored)
                        return `($${idParam}, $1, $${identifierParam}, $2, NOW(), NOW(), false)`
                    })
                    .join(', ')
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO ${replicaSchema}.posthog_messagerecipientpreference
                        (id, team_id, identifier, preferences, created_at, updated_at, deleted)
                     VALUES ${replicaPlaceholders}`,
                    replicaValues,
                    'testSeedReplica'
                )

                const freshManager = new RecipientsManagerService(splitRouter)
                const cachedReplica = await freshManager.get({
                    teamId: team.id,
                    identifier: 'alice@example.com',
                    anyCase: true,
                })
                expect(cachedReplica?.preferences).toEqual({ 'cat-1': 'OPTED_IN' })

                const smallBatchBefore = await readPrimaryScans()
                const smallBatch = await Promise.all([
                    freshManager.getFresh({ teamId: team.id, identifier: seededRecipients[0].lookup, anyCase: true }),
                    freshManager.getFresh({ teamId: team.id, identifier: seededRecipients[1].lookup, anyCase: true }),
                    freshManager.getFresh({ teamId: team.id, identifier: 'missing-small@example.com', anyCase: true }),
                ])
                const smallBatchScans = (await readPrimaryScans()) - smallBatchBefore

                const largeBatchBefore = await readPrimaryScans()
                const largeBatch = await Promise.all([
                    ...seededRecipients.map((recipient) =>
                        freshManager.getFresh({ teamId: team.id, identifier: recipient.lookup, anyCase: true })
                    ),
                    freshManager.getFresh({ teamId: team.id, identifier: 'missing-large@example.com', anyCase: true }),
                ])
                const largeBatchScans = (await readPrimaryScans()) - largeBatchBefore

                expect(smallBatchScans).toBeGreaterThan(0)
                expect(largeBatchScans).toBeGreaterThan(0)
                expect(largeBatchScans).toBeLessThanOrEqual(smallBatchScans)
                expect(smallBatch[0]?.preferences).toEqual({ 'cat-1': 'OPTED_OUT' })
                expect(smallBatch[1]?.preferences).toEqual({ 'cat-1': 'OPTED_IN' })
                expect(smallBatch[2]).toBeNull()
                for (let index = 0; index < seededRecipients.length; index += 1) {
                    expect(largeBatch[index]?.preferences).toEqual({ 'cat-1': seededRecipients[index].primaryStatus })
                }
                expect(largeBatch[seededRecipients.length]).toBeNull()

                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE ${primarySchema}.posthog_messagerecipientpreference
                     SET preferences = $1 WHERE team_id = $2 AND identifier = $3`,
                    [JSON.stringify({ 'cat-1': 'OPTED_OUT' }), team.id, seededRecipients[1].stored],
                    'testUpdatePrimaryRecipient'
                )
                const updated = await freshManager.getFresh({
                    teamId: team.id,
                    identifier: seededRecipients[1].lookup,
                    anyCase: true,
                })
                expect(updated?.preferences).toEqual({ 'cat-1': 'OPTED_OUT' })
            } finally {
                await splitRouter.end()
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `DROP SCHEMA IF EXISTS ${primarySchema} CASCADE; DROP SCHEMA IF EXISTS ${replicaSchema} CASCADE;`,
                    [],
                    'testDropPrimaryAndReplicaSchemas'
                )
            }
        })

        it('does not attach a new fresh read to a primary query that already started', async () => {
            await createRecipient(team.id, 'user@example.com', { 'cat-1': 'OPTED_IN' })

            let releaseFirstQuery!: () => void
            let firstQueryStarted!: () => void
            const firstStarted = new Promise<void>((resolve) => {
                firstQueryStarted = resolve
            })
            let heldFirst = false

            const freshManager = new RecipientsManagerService({
                query: async (use, query, values, tag) => {
                    const result = await hub.postgres.query(use, query, values, tag)
                    if (!heldFirst) {
                        heldFirst = true
                        firstQueryStarted()
                        await new Promise<void>((resolve) => {
                            releaseFirstQuery = resolve
                        })
                    }
                    return result
                },
            })

            const firstRead = freshManager.getFresh({
                teamId: team.id,
                identifier: 'user@example.com',
                anyCase: true,
            })
            await firstStarted

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_messagerecipientpreference SET preferences = $1 WHERE team_id = $2 AND identifier = $3`,
                [JSON.stringify({ 'cat-1': 'OPTED_OUT' }), team.id, 'user@example.com'],
                'testOptOutWhileInFlight'
            )

            const secondRead = freshManager.getFresh({
                teamId: team.id,
                identifier: 'user@example.com',
                anyCase: true,
            })
            releaseFirstQuery()

            const [first, second] = await Promise.all([firstRead, secondRead])

            expect(first?.preferences).toEqual({ 'cat-1': 'OPTED_IN' })
            expect(second?.preferences).toEqual({ 'cat-1': 'OPTED_OUT' })
        })
    })
})
