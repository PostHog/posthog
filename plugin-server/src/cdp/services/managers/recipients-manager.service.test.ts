import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'
import { UUIDT } from '~/utils/utils'

import { RecipientGetArgs, RecipientsManagerService } from './recipients-manager.service'

describe('RecipientsManager', () => {
    let hub: Hub
    let manager: RecipientsManagerService
    let team: Team
    let team2: Team

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new RecipientsManagerService(hub)
        team = await getFirstTeam(hub)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!
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
})
