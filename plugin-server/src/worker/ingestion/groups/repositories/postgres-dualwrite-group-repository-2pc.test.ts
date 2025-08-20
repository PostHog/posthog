import { DateTime } from 'luxon'

import { insertRow, resetTestDatabase } from '../../../../../tests/helpers/sql'
import {
    GroupTypeIndex,
    Hub,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    TeamId,
} from '../../../../types'
import { closeHub, createHub } from '../../../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { RaceConditionError, UUIDT } from '../../../../utils/utils'
import { PostgresDualWriteGroupRepository } from './postgres-dualwrite-group-repository'

jest.mock('../../../../utils/logger')

describe('PostgresDualWriteGroupRepository 2PC Dual-Write Tests', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let repository: PostgresDualWriteGroupRepository

    async function setupMigrationDbForGroups(migrationPostgres: PostgresRouter): Promise<void> {
        // Drop existing tables
        await migrationPostgres.query(
            PostgresUse.PERSONS_WRITE,
            `DROP TABLE IF EXISTS posthog_group CASCADE`,
            [],
            'drop-group-table'
        )

        // Create group table in migration database
        await migrationPostgres.query(
            PostgresUse.PERSONS_WRITE,
            `
            CREATE TABLE IF NOT EXISTS posthog_group (
                team_id INT NOT NULL,
                group_type_index SMALLINT NOT NULL,
                group_key VARCHAR(400) NOT NULL,
                group_properties JSONB,
                properties_last_updated_at JSONB,
                properties_last_operation JSONB,
                created_at TIMESTAMPTZ,
                version BIGINT DEFAULT 0,
                PRIMARY KEY (team_id, group_type_index, group_key)
            );
            `,
            [],
            'create-group-table'
        )
    }

    async function cleanupPrepared(hub: Hub) {
        const routers = [hub.db.postgres, hub.db.postgresPersonMigration]
        for (const r of routers) {
            const res = await r.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT gid FROM pg_prepared_xacts WHERE gid LIKE 'dualwrite:%'`,
                [],
                'list-prepared'
            )
            for (const row of res.rows) {
                await r.query(
                    PostgresUse.PERSONS_WRITE,
                    `ROLLBACK PREPARED '${String(row.gid).replace(/'/g, "''")}'`,
                    [],
                    'rollback-prepared'
                )
            }
        }
    }

    async function getFirstTeam(postgres: PostgresRouter): Promise<any> {
        const teams = await postgres.query(
            PostgresUse.COMMON_WRITE,
            'SELECT * FROM posthog_team LIMIT 1',
            [],
            'getFirstTeam'
        )
        return teams.rows[0]
    }

    async function assertConsistencyAcrossDatabases(
        primaryRouter: PostgresRouter,
        secondaryRouter: PostgresRouter,
        query: string,
        params: any[],
        primaryTag: string,
        secondaryTag: string
    ) {
        const [primary, secondary] = await Promise.all([
            primaryRouter.query(PostgresUse.PERSONS_READ, query, params, primaryTag),
            secondaryRouter.query(PostgresUse.PERSONS_READ, query, params, secondaryTag),
        ])
        expect(primary.rows).toEqual(secondary.rows)
    }

    function mockDatabaseError(
        router: PostgresRouter,
        error: Error,
        tagPattern: string
    ) {
        const originalQuery = router.query.bind(router)
        return jest.spyOn(router, 'query').mockImplementation((use: any, text: any, params: any, tag: string) => {
            if (tag && tag.startsWith(tagPattern)) {
                throw error
            }
            return originalQuery(use, text, params, tag)
        })
    }

    async function insertTestTeam(postgres: PostgresRouter, teamId: number) {
        // First create the project that the team references
        await insertRow(postgres, 'posthog_project', {
            id: teamId,
            organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
            name: `Test Project ${teamId}`,
            created_at: new Date().toISOString(),
        })

        // Then create the team
        await insertRow(postgres, 'posthog_team', {
            id: teamId,
            name: `Test Team ${teamId}`,
            organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
            project_id: teamId,
            uuid: new UUIDT().toString(),
            api_token: `test-api-token-${teamId}`,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            anonymize_ips: false,
            completed_snippet_onboarding: true,
            ingested_event: true,
            session_recording_opt_in: true,
            plugins_opt_in: false,
            opt_out_capture: false,
            is_demo: false,
            test_account_filters: [],
            timezone: 'UTC',
            data_attributes: [],
            person_display_name_properties: [],
            access_control: false,
            base_currency: 'USD',
            session_recording_retention_period: 'legacy',
            app_urls: [],
            event_names: [],
            event_names_with_usage: [],
            event_properties: [],
            event_properties_with_usage: [],
            event_properties_numerical: [],
        })
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        migrationPostgres = hub.db.postgresPersonMigration
        await setupMigrationDbForGroups(migrationPostgres)

        repository = new PostgresDualWriteGroupRepository(postgres, migrationPostgres, {
            comparisonEnabled: true
        })

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)

        // Set up test team
        await insertTestTeam(postgres, 1)
    })

    afterEach(async () => {
        await cleanupPrepared(hub)
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('insertGroup() 2PC tests', () => {
        it('writes to both primary and secondary (happy path)', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-group-1'
            const groupProperties = { name: 'Test Group', type: 'company' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const propertiesLastUpdatedAt: PropertiesLastUpdatedAt = {}
            const propertiesLastOperation: PropertiesLastOperation = {}

            const version = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(version).toBe(1)

            // Verify both databases have the group
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3',
                [teamId, groupTypeIndex, groupKey],
                'verify-primary-insert'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3',
                [teamId, groupTypeIndex, groupKey],
                'verify-secondary-insert'
            )

            expect(primary.rows.length).toBe(1)
            expect(secondary.rows.length).toBe(1)
            expect(primary.rows[0].group_properties).toEqual(groupProperties)
            expect(secondary.rows[0].group_properties).toEqual(groupProperties)
        })

        it('rolls back both when secondary write fails', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-rollback-1'
            const groupProperties = { name: 'Rollback Test' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'insertGroup')
                .mockRejectedValue(new Error('simulated secondary failure'))

            await expect(
                repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    {},
                    {}
                )
            ).rejects.toThrow('simulated secondary failure')

            spy.mockRestore()

            // Verify neither database has the group
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-rollback'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-secondary-rollback'
            )

            expect(primary.rows.length).toBe(0)
            expect(secondary.rows.length).toBe(0)
        })

        it.skip('rolls back when primary database fails - requires complex mocking', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-primary-fail'
            const groupProperties = { name: 'Primary Fail Test' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary database connection lost'),
                'insertGroup'
            )

            await expect(
                repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    {},
                    {}
                )
            ).rejects.toThrow('primary database connection lost')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-group-rollback',
                'verify-secondary-group-rollback'
            )

            const groupCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-empty-group'
            )
            expect(groupCheck.rows.length).toBe(0)
        })

        it.skip('rolls back when secondary database fails - requires complex mocking', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-secondary-fail'
            const groupProperties = { name: 'Secondary Fail Test' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary database connection lost'),
                'insertGroup'
            )

            await expect(
                repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    {},
                    {}
                )
            ).rejects.toThrow('secondary database connection lost')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-group-rollback',
                'verify-secondary-group-rollback'
            )

            const groupCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-empty-group'
            )
            expect(groupCheck.rows.length).toBe(0)
        })

        it('handles race condition errors properly', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-race-condition'
            const groupProperties = { name: 'Race Condition Test' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            // First insert
            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                {},
                {}
            )

            // Second insert with same key should throw RaceConditionError
            // TODO: This currently returns undefined instead of throwing
            await expect(
                repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    {},
                    {}
                )
            ).rejects.toThrow(RaceConditionError)

            // Verify only one group exists
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-race-condition'
            )
            expect(primary.rows.length).toBe(1)
        })
    })

    describe('updateGroup() 2PC tests', () => {
        it('updates both primary and secondary (happy path)', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-update-1'
            const initialProperties = { name: 'Initial Name' }
            const updatedProperties = { name: 'Updated Name', newProp: 'value' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            // First insert a group
            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                initialProperties,
                createdAt,
                {},
                {}
            )

            // Now update it
            const version = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                updatedProperties,
                createdAt,
                {},
                {},
                'test-update'
            )

            expect(version).toBe(2)

            // Verify both databases have the updated group
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-update'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-secondary-update'
            )

            expect(primary.rows[0].group_properties).toEqual(updatedProperties)
            expect(secondary.rows[0].group_properties).toEqual(updatedProperties)
            expect(Number(primary.rows[0].version)).toBe(2)
            expect(Number(secondary.rows[0].version)).toBe(2)
        })

        it('rolls back both when secondary update fails', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-update-rollback'
            const initialProperties = { name: 'Initial' }
            const updatedProperties = { name: 'Should Not Update' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            // First insert a group
            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                initialProperties,
                createdAt,
                {},
                {}
            )

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'updateGroup')
                .mockRejectedValue(new Error('simulated secondary update failure'))

            await expect(
                repository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    updatedProperties,
                    createdAt,
                    {},
                    {},
                    'test-fail'
                )
            ).rejects.toThrow('simulated secondary update failure')

            spy.mockRestore()

            // Verify both databases still have the original properties
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-not-updated'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-secondary-not-updated'
            )

            expect(primary.rows[0].group_properties).toEqual(initialProperties)
            expect(secondary.rows[0].group_properties).toEqual(initialProperties)
            expect(Number(primary.rows[0].version)).toBe(1)
            expect(Number(secondary.rows[0].version)).toBe(1)
        })

        it.skip('rolls back when primary database fails - requires complex mocking', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-update-primary-fail'
            const initialProperties = { name: 'Original' }
            const updatedProperties = { name: 'Updated' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                initialProperties,
                createdAt,
                {},
                {}
            )

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary update failed'),
                'updateGroup'
            )

            await expect(
                repository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    updatedProperties,
                    createdAt,
                    {},
                    {},
                    'test-primary-fail'
                )
            ).rejects.toThrow('primary update failed')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT group_properties FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-unchanged',
                'verify-secondary-unchanged'
            )

            const groupCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-properties'
            )
            expect(groupCheck.rows[0].group_properties).toEqual(initialProperties)
        })

        it.skip('rolls back when secondary database fails - requires complex mocking', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-update-secondary-fail'
            const initialProperties = { name: 'Original' }
            const updatedProperties = { name: 'Updated' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                initialProperties,
                createdAt,
                {},
                {}
            )

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary update failed'),
                'updateGroup'
            )

            await expect(
                repository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    updatedProperties,
                    createdAt,
                    {},
                    {},
                    'test-secondary-fail'
                )
            ).rejects.toThrow('secondary update failed')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT group_properties FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-unchanged',
                'verify-secondary-unchanged'
            )

            const groupCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-properties'
            )
            expect(groupCheck.rows[0].group_properties).toEqual(initialProperties)
        })

        it('returns undefined when group does not exist', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'non-existent-group'
            const groupProperties = { name: 'Should not update' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            const result = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                {},
                {},
                'test-non-existent'
            )

            expect(result).toBeUndefined()
        })
    })

    describe('updateGroupOptimistically() non-2PC test', () => {
        it('updates secondary on primary success (happy path)', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-optimistic-1'
            const initialProperties = { name: 'Initial' }
            const updatedProperties = { name: 'Updated Optimistically' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            // Insert group
            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                initialProperties,
                createdAt,
                {},
                {}
            )

            // Update optimistically with correct version
            const version = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                1, // expected version
                updatedProperties,
                createdAt,
                {},
                {}
            )

            expect(version).toBe(2)

            // Verify both databases have the updated group
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-optimistic'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-secondary-optimistic'
            )

            expect(primary.rows[0].group_properties).toEqual(updatedProperties)
            expect(secondary.rows[0].group_properties).toEqual(updatedProperties)
            expect(Number(primary.rows[0].version)).toBe(2)
            expect(Number(secondary.rows[0].version)).toBe(2)
        })

        it('returns undefined when version mismatch', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-optimistic-mismatch'
            const initialProperties = { name: 'Initial' }
            const updatedProperties = { name: 'Should not update' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            // Insert group (version 0)
            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                initialProperties,
                createdAt,
                {},
                {}
            )

            // Try to update with wrong expected version
            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                5, // wrong expected version
                updatedProperties,
                createdAt,
                {},
                {}
            )

            expect(result).toBeUndefined()

            // Verify group is unchanged
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-unchanged'
            )
            expect(primary.rows[0].group_properties).toEqual(initialProperties)
            expect(Number(primary.rows[0].version)).toBe(1)
        })

        it('does not rollback primary when secondary fails (non-2PC)', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-optimistic-secondary-fail'
            const initialProperties = { name: 'Initial' }
            const updatedProperties = { name: 'Updated in primary only' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                initialProperties,
                createdAt,
                {},
                {}
            )

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'updateGroupOptimistically')
                .mockRejectedValue(new Error('secondary optimistic update failure'))

            // Should NOT throw - returns primary result even if secondary fails
            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                1,
                updatedProperties,
                createdAt,
                {},
                {}
            )
            
            expect(result).toBe(2) // Primary succeeded

            spy.mockRestore()

            // Primary should have been updated (non-2PC, no rollback)
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-primary-updated'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, groupKey],
                'verify-secondary-not-updated'
            )

            expect(primary.rows[0].group_properties).toEqual(updatedProperties)
            expect(secondary.rows[0].group_properties).toEqual(initialProperties)
            expect(Number(primary.rows[0].version)).toBe(2)
            expect(Number(secondary.rows[0].version)).toBe(1)
        })
    })

    describe('inTransaction() 2PC tests', () => {
        it('should execute multiple operations atomically within a transaction (happy path)', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            const result = await repository.inTransaction('test-multi-operation', async (tx) => {
                // Insert first group
                const version1 = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'tx-group-1',
                    { name: 'Transaction Group 1' },
                    createdAt,
                    {},
                    {}
                )

                // Insert second group
                const version2 = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'tx-group-2',
                    { name: 'Transaction Group 2' },
                    createdAt,
                    {},
                    {}
                )

                // Update first group
                const updatedVersion = await tx.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'tx-group-1',
                    { name: 'Updated Transaction Group 1', status: 'active' },
                    createdAt,
                    {},
                    {},
                    'tx-update'
                )

                return { version1, version2, updatedVersion }
            })

            expect(result.version1).toBe(1)
            expect(result.version2).toBe(1)
            expect(result.updatedVersion).toBe(2)

            // Verify both groups exist in both databases
            const group1Primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-group-1'],
                'verify-group1-primary'
            )
            const group1Secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-group-1'],
                'verify-group1-secondary'
            )

            expect(group1Primary.rows.length).toBe(1)
            expect(group1Secondary.rows.length).toBe(1)
            expect(group1Primary.rows[0].group_properties).toEqual({ 
                name: 'Updated Transaction Group 1', 
                status: 'active' 
            })
            expect(group1Secondary.rows[0].group_properties).toEqual({ 
                name: 'Updated Transaction Group 1', 
                status: 'active' 
            })

            const group2Primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-group-2'],
                'verify-group2-primary'
            )
            const group2Secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-group-2'],
                'verify-group2-secondary'
            )

            expect(group2Primary.rows.length).toBe(1)
            expect(group2Secondary.rows.length).toBe(1)
        })

        it('should rollback all operations when any operation fails within transaction', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            // Mock to make second insert fail on secondary
            const spy = jest.spyOn((repository as any).secondaryRepo, 'insertGroup')
            spy.mockResolvedValueOnce(0) // First insert succeeds
            spy.mockRejectedValueOnce(new Error('simulated insertGroup failure in transaction'))

            await expect(
                repository.inTransaction('test-rollback', async (tx) => {
                    // First insert should succeed initially
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'tx-rollback-1',
                        { name: 'Will Rollback 1' },
                        createdAt,
                        {},
                        {}
                    )

                    // Second insert should fail
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'tx-rollback-2',
                        { name: 'Will Rollback 2' },
                        createdAt,
                        {},
                        {}
                    )

                    return 'should not reach here'
                })
            ).rejects.toThrow('simulated insertGroup failure in transaction')

            spy.mockRestore()

            // Verify nothing was persisted to either database
            const check1Primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-rollback-1'],
                'verify-rollback-1-primary'
            )
            const check1Secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-rollback-1'],
                'verify-rollback-1-secondary'
            )

            expect(check1Primary.rows.length).toBe(0)
            expect(check1Secondary.rows.length).toBe(0)

            const check2Primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-rollback-2'],
                'verify-rollback-2-primary'
            )
            const check2Secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'tx-rollback-2'],
                'verify-rollback-2-secondary'
            )

            expect(check2Primary.rows.length).toBe(0)
            expect(check2Secondary.rows.length).toBe(0)
        })

        it('should handle race condition errors within transaction', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            // First create a group
            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                'existing-group',
                { name: 'Existing' },
                createdAt,
                {},
                {}
            )

            // Try to create with same key in transaction
            await expect(
                repository.inTransaction('test-race-condition', async (tx) => {
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'existing-group',
                        { name: 'Should cause race condition' },
                        createdAt,
                        {},
                        {}
                    )
                    return 'should not reach here'
                })
            ).rejects.toThrow(RaceConditionError)

            // Verify only original group exists
            const check = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'existing-group'],
                'verify-race-condition'
            )
            expect(check.rows.length).toBe(1)
            expect(check.rows[0].group_properties).toEqual({ name: 'Existing' })
        })

        it('should propagate errors correctly through transaction boundaries', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const customError = new Error('Custom transaction error')

            await expect(
                repository.inTransaction('test-error-propagation', async (tx) => {
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'error-test-group',
                        { name: 'Error Test' },
                        createdAt,
                        {},
                        {}
                    )

                    throw customError
                })
            ).rejects.toThrow('Custom transaction error')

            // Verify group was rolled back
            const check = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'error-test-group'],
                'verify-error-rollback'
            )
            expect(check.rows.length).toBe(0)
        })

        it.skip('should handle primary database failure within transaction - requires complex mocking', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary database failure in transaction'),
                'updateGroup'
            )

            await expect(
                repository.inTransaction('test-primary-failure', async (tx) => {
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'primary-fail-group',
                        { name: 'Initial' },
                        createdAt,
                        {},
                        {}
                    )

                    // This should fail
                    await tx.updateGroup(
                        teamId,
                        groupTypeIndex,
                        'primary-fail-group',
                        { name: 'Updated' },
                        createdAt,
                        {},
                        {},
                        'test-fail'
                    )

                    return 'should not reach here'
                })
            ).rejects.toThrow('primary database failure in transaction')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'primary-fail-group'],
                'verify-primary-tx-rollback',
                'verify-secondary-tx-rollback'
            )
        })

        it('should handle secondary database failure within transaction', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary database failure in transaction'),
                'insertGroup'
            )

            await expect(
                repository.inTransaction('test-secondary-failure', async (tx) => {
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'secondary-fail-group',
                        { name: 'Initial' },
                        createdAt,
                        {},
                        {}
                    )

                    return 'should not reach here'
                })
            ).rejects.toThrow('secondary database failure in transaction')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'secondary-fail-group'],
                'verify-primary-no-commit',
                'verify-secondary-no-commit'
            )
        })

        it('should handle mixed direct and transactional calls correctly', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            // Create a group outside transaction
            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                'outside-tx',
                { location: 'outside' },
                createdAt,
                {},
                {}
            )

            // Now use it within a transaction
            const txResult = await repository.inTransaction('test-mixed-calls', async (tx) => {
                // Update the group created outside
                const updatedVersion = await tx.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'outside-tx',
                    { location: 'updated-inside', new_prop: 'added' },
                    createdAt,
                    {},
                    {},
                    'tx-update'
                )

                // Create a new group within the transaction
                const newVersion = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'inside-tx',
                    { location: 'inside' },
                    createdAt,
                    {},
                    {}
                )

                return { updatedVersion, newVersion }
            })

            // Verify the mixed operations worked
            const updatedOutside = await repository.fetchGroup(teamId, groupTypeIndex, 'outside-tx')
            const insideGroup = await repository.fetchGroup(teamId, groupTypeIndex, 'inside-tx')

            expect(updatedOutside).toBeDefined()
            expect(updatedOutside?.group_properties.location).toBe('updated-inside')
            expect(updatedOutside?.group_properties.new_prop).toBe('added')
            expect(insideGroup).toBeDefined()
            expect(insideGroup?.group_properties.location).toBe('inside')
            expect(txResult.updatedVersion).toBe(2)
            expect(txResult.newVersion).toBe(1)
        })
    })

    describe('Comparison and metrics', () => {
        it('tracks version mismatches between databases', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-metrics'
            const groupProperties = { name: 'Metrics Test' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            // Spy on comparison method
            const compareSpy = jest.spyOn((repository as any), 'compareInsertGroupResults')

            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                {},
                {}
            )

            expect(compareSpy).toHaveBeenCalledWith(1, 1)
            compareSpy.mockRestore()
        })
    })
})