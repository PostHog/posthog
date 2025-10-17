import { DateTime } from 'luxon'

import { insertRow, resetTestDatabase } from '../../../../../tests/helpers/sql'
import {
    GroupTypeIndex,
    Hub,
    ProjectId,
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
        await migrationPostgres.query(
            PostgresUse.PERSONS_WRITE,
            `DROP TABLE IF EXISTS posthog_group CASCADE`,
            [],
            'drop-group-table'
        )

        await migrationPostgres.query(
            PostgresUse.PERSONS_WRITE,
            `DROP TABLE IF EXISTS posthog_grouptypemapping CASCADE`,
            [],
            'drop-grouptypemapping-table'
        )

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

        await migrationPostgres.query(
            PostgresUse.PERSONS_WRITE,
            `
            CREATE TABLE IF NOT EXISTS posthog_grouptypemapping (
                id SERIAL PRIMARY KEY,
                team_id INT NOT NULL,
                project_id INT NOT NULL,
                group_type VARCHAR(400) NOT NULL,
                group_type_index SMALLINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, group_type),
                UNIQUE(project_id, group_type_index)
            );
            `,
            [],
            'create-grouptypemapping-table'
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

    function mockDatabaseError(router: PostgresRouter, error: Error, tagPattern: string) {
        const originalQuery = router.query.bind(router)
        return jest.spyOn(router, 'query').mockImplementation((use: any, text: any, params: any, tag: string) => {
            if (tag && tag.startsWith(tagPattern)) {
                throw error
            }
            return originalQuery(use, text, params, tag)
        })
    }

    async function insertTestTeam(postgres: PostgresRouter, teamId: number) {
        await insertRow(postgres, 'posthog_project', {
            id: teamId,
            organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
            name: `Test Project ${teamId}`,
            created_at: new Date().toISOString(),
        })

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
            session_recording_retention_period: '30d',
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
            comparisonEnabled: true,
        })

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)

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
                repository.insertGroup(teamId, groupTypeIndex, groupKey, groupProperties, createdAt, {}, {})
            ).rejects.toThrow('simulated secondary failure')

            spy.mockRestore()

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

            const mockSpy = mockDatabaseError(postgres, new Error('primary database connection lost'), 'insertGroup')

            await expect(
                repository.insertGroup(teamId, groupTypeIndex, groupKey, groupProperties, createdAt, {}, {})
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
                repository.insertGroup(teamId, groupTypeIndex, groupKey, groupProperties, createdAt, {}, {})
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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, groupProperties, createdAt, {}, {})

            await expect(
                repository.insertGroup(teamId, groupTypeIndex, groupKey, groupProperties, createdAt, {}, {})
            ).rejects.toThrow(RaceConditionError)

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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, initialProperties, createdAt, {}, {})

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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, initialProperties, createdAt, {}, {})

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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, initialProperties, createdAt, {}, {})

            const mockSpy = mockDatabaseError(postgres, new Error('primary update failed'), 'updateGroup')

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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, initialProperties, createdAt, {}, {})

            const mockSpy = mockDatabaseError(migrationPostgres, new Error('secondary update failed'), 'updateGroup')

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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, initialProperties, createdAt, {}, {})

            const version = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                1,
                updatedProperties,
                createdAt,
                {},
                {}
            )

            expect(version).toBe(2)

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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, initialProperties, createdAt, {}, {})

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                5,
                updatedProperties,
                createdAt,
                {},
                {}
            )

            expect(result).toBeUndefined()

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

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, initialProperties, createdAt, {}, {})

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'updateGroupOptimistically')
                .mockRejectedValue(new Error('secondary optimistic update failure'))

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

            expect(result).toBe(2)

            spy.mockRestore()

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
                const version1 = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'tx-group-1',
                    { name: 'Transaction Group 1' },
                    createdAt,
                    {},
                    {}
                )

                const version2 = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'tx-group-2',
                    { name: 'Transaction Group 2' },
                    createdAt,
                    {},
                    {}
                )

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
                status: 'active',
            })
            expect(group1Secondary.rows[0].group_properties).toEqual({
                name: 'Updated Transaction Group 1',
                status: 'active',
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

            const spy = jest.spyOn((repository as any).secondaryRepo, 'insertGroup')
            spy.mockResolvedValueOnce(0)
            spy.mockRejectedValueOnce(new Error('simulated insertGroup failure in transaction'))

            await expect(
                repository.inTransaction('test-rollback', async (tx) => {
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'tx-rollback-1',
                        { name: 'Will Rollback 1' },
                        createdAt,
                        {},
                        {}
                    )

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

            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                'existing-group',
                { name: 'Existing' },
                createdAt,
                {},
                {}
            )

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

            await repository.insertGroup(
                teamId,
                groupTypeIndex,
                'outside-tx',
                { location: 'outside' },
                createdAt,
                {},
                {}
            )

            const txResult = await repository.inTransaction('test-mixed-calls', async (tx) => {
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

    describe('insertGroupType() 2PC tests', () => {
        const teamId = 1 as TeamId
        const projectId = 1 as ProjectId

        it('writes to both primary and secondary (happy path)', async () => {
            const [groupTypeIndex, isInsert] = await repository.insertGroupType(teamId, projectId, 'company', 0)

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(true)

            // Verify in both databases
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, projectId, 'company'],
                'verify-primary-group-type'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, projectId, 'company'],
                'verify-secondary-group-type'
            )

            expect(primary.rows.length).toBe(1)
            expect(secondary.rows.length).toBe(1)

            // Check primary database result
            expect(primary.rows[0].team_id).toBe(teamId)
            expect(Number(primary.rows[0].project_id)).toBe(projectId)
            expect(primary.rows[0].group_type).toBe('company')
            expect(primary.rows[0].group_type_index).toBe(0)

            // Check secondary database result
            expect(secondary.rows[0].team_id).toBe(teamId)
            expect(Number(secondary.rows[0].project_id)).toBe(projectId)
            expect(secondary.rows[0].group_type).toBe('company')
            expect(secondary.rows[0].group_type_index).toBe(0)
        })

        it('returns existing group type without inserting when already exists', async () => {
            // First insert
            await repository.insertGroupType(teamId, projectId, 'organization', 0)

            // Second insert should return existing
            const [groupTypeIndex, isInsert] = await repository.insertGroupType(teamId, projectId, 'organization', 0)

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(false)

            // Verify only one record in each database
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, projectId, 'organization'],
                'verify-primary-single'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, projectId, 'organization'],
                'verify-secondary-single'
            )

            expect(primary.rows.length).toBe(1)
            expect(secondary.rows.length).toBe(1)
        })

        it('handles index conflicts by incrementing consistently', async () => {
            // Insert multiple group types
            const [index1, isInsert1] = await repository.insertGroupType(teamId, projectId, 'type1', 0)
            const [index2, isInsert2] = await repository.insertGroupType(teamId, projectId, 'type2', 0)
            const [index3, isInsert3] = await repository.insertGroupType(teamId, projectId, 'type3', 0)

            expect(index1).toBe(0)
            expect(index2).toBe(1)
            expect(index3).toBe(2)
            expect(isInsert1).toBe(true)
            expect(isInsert2).toBe(true)
            expect(isInsert3).toBe(true)

            // Verify consistency between databases
            const primaryCount = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) as count FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2',
                [teamId, projectId],
                'count-primary'
            )
            const secondaryCount = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) as count FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2',
                [teamId, projectId],
                'count-secondary'
            )

            expect(primaryCount.rows[0].count).toBe('3')
            expect(secondaryCount.rows[0].count).toBe('3')
        })

        it('respects maximum group types limit consistently', async () => {
            // Insert 5 group types (the maximum)
            for (let i = 0; i < 5; i++) {
                const [index, isInsert] = await repository.insertGroupType(teamId, projectId, `type_${i}`, i)
                expect(index).toBe(i)
                expect(isInsert).toBe(true)
            }

            // Try to insert the 6th group type (should fail)
            const [index6, isInsert6] = await repository.insertGroupType(teamId, projectId, 'type_6', 5)
            expect(index6).toBe(null)
            expect(isInsert6).toBe(false)

            // Verify both databases have exactly 5 records
            const primaryCount = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) as count FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2',
                [teamId, projectId],
                'count-primary-max'
            )
            const secondaryCount = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) as count FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2',
                [teamId, projectId],
                'count-secondary-max'
            )

            expect(primaryCount.rows[0].count).toBe('5')
            expect(secondaryCount.rows[0].count).toBe('5')
        })

        it('rolls back when secondary write fails', async () => {
            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'insertGroupType')
                .mockRejectedValue(new Error('simulated secondary failure'))

            await expect(repository.insertGroupType(teamId, projectId, 'failtype', 0)).rejects.toThrow(
                'simulated secondary failure'
            )

            spy.mockRestore()

            // Verify no records in either database
            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, projectId, 'failtype'],
                'verify-primary-rollback'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, projectId, 'failtype'],
                'verify-secondary-rollback'
            )

            expect(primary.rows.length).toBe(0)
            expect(secondary.rows.length).toBe(0)
        })

        it('works within a transaction', async () => {
            const result = await repository.inTransaction('test insertGroupType transaction', async (tx) => {
                const groupTypeResult = await tx.insertGroupType(teamId, projectId, 'txtype', 0)

                // Also insert a group to verify the transaction context
                await tx.insertGroup(
                    teamId,
                    0 as GroupTypeIndex,
                    'txgroup',
                    { name: 'Transaction Group' },
                    DateTime.now(),
                    {},
                    {}
                )

                return groupTypeResult
            })

            expect(result).toEqual([0, true])

            // Verify both group type and group exist in both databases
            const primaryGroupType = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, projectId, 'txtype'],
                'verify-primary-tx-grouptype'
            )
            const primaryGroup = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'txgroup'],
                'verify-primary-tx-group'
            )

            expect(primaryGroupType.rows.length).toBe(1)
            expect(primaryGroup.rows.length).toBe(1)
        })

        it('compares results between databases when comparison is enabled', async () => {
            // Create a repository with comparison enabled
            const comparingRepository = new PostgresDualWriteGroupRepository(postgres, migrationPostgres, {
                comparisonEnabled: true,
            })

            const [groupTypeIndex, isInsert] = await comparingRepository.insertGroupType(
                teamId,
                projectId,
                'comparetype',
                0
            )

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(true)

            // Should not throw despite comparison being enabled (successful comparison)
        })
    })

    describe('Comparison and metrics', () => {
        it('tracks version mismatches between databases', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupKey = 'test-metrics'
            const groupProperties = { name: 'Metrics Test' }
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

            const compareSpy = jest.spyOn(repository as any, 'compareInsertGroupResults')

            await repository.insertGroup(teamId, groupTypeIndex, groupKey, groupProperties, createdAt, {}, {})

            expect(compareSpy).toHaveBeenCalledWith(1, 1)
            compareSpy.mockRestore()
        })
    })

    describe('fetchGroupTypesByProjectIds() 2PC tests', () => {
        const teamId = 1 as TeamId
        const projectId = 1 as ProjectId

        it('should fetch from primary repository only', async () => {
            // Insert group types using the dual-write repository (writes to both)
            await repository.insertGroupType(teamId, projectId, 'company', 0)
            await repository.insertGroupType(teamId, projectId, 'organization', 1)

            const result = await repository.fetchGroupTypesByProjectIds([projectId])

            expect(result).toEqual({
                [projectId]: [
                    { group_type: 'company', group_type_index: 0 },
                    { group_type: 'organization', group_type_index: 1 },
                ],
            })
        })

        it('should return empty object for empty project IDs array', async () => {
            const result = await repository.fetchGroupTypesByProjectIds([])
            expect(result).toEqual({})
        })

        it('should return empty arrays for projects with no group types', async () => {
            const result = await repository.fetchGroupTypesByProjectIds([projectId])
            expect(result).toEqual({
                [projectId]: [],
            })
        })

        it('should handle multiple projects', async () => {
            const localTeamId1 = 15 as TeamId
            const localTeamId2 = 16 as TeamId
            const localProjectId1 = 15 as ProjectId
            const localProjectId2 = 16 as ProjectId

            await insertTestTeam(postgres, localTeamId1)
            await insertTestTeam(postgres, localTeamId2)

            // Insert group types for both projects
            await repository.insertGroupType(localTeamId1, localProjectId1, 'company', 0)
            await repository.insertGroupType(localTeamId2, localProjectId2, 'organization', 0)

            const result = await repository.fetchGroupTypesByProjectIds([localProjectId1, localProjectId2])

            expect(result).toEqual({
                [localProjectId1]: [{ group_type: 'company', group_type_index: 0 }],
                [localProjectId2]: [{ group_type: 'organization', group_type_index: 0 }],
            })
        })

        it('should read from primary only (not secondary)', async () => {
            // Insert directly to primary only using postgres client
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_grouptypemapping (team_id, project_id, group_type, group_type_index, created_at) VALUES ($1, $2, $3, $4, $5)',
                [teamId, projectId, 'primary_only', 0, new Date()],
                'insert-primary-only'
            )

            const result = await repository.fetchGroupTypesByProjectIds([projectId])

            expect(result).toEqual({
                [projectId]: [{ group_type: 'primary_only', group_type_index: 0 }],
            })

            // Verify secondary has no data
            const secondaryResult = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE project_id = $1',
                [projectId],
                'test-secondary-check'
            )
            expect(secondaryResult.rows).toHaveLength(0)
        })
    })

    describe('fetchGroupTypesByTeamIds() 2PC tests', () => {
        const teamId = 1 as TeamId
        const projectId = 1 as ProjectId

        it('should fetch from primary repository only', async () => {
            // Insert group types using the dual-write repository (writes to both)
            await repository.insertGroupType(teamId, projectId, 'company', 0)
            await repository.insertGroupType(teamId, projectId, 'organization', 1)

            const result = await repository.fetchGroupTypesByTeamIds([teamId])

            expect(result).toEqual({
                [teamId]: [
                    { group_type: 'company', group_type_index: 0 },
                    { group_type: 'organization', group_type_index: 1 },
                ],
            })
        })

        it('should return empty object for empty team IDs array', async () => {
            const result = await repository.fetchGroupTypesByTeamIds([])
            expect(result).toEqual({})
        })

        it('should handle multiple teams', async () => {
            const localTeamId1 = 30 as TeamId
            const localTeamId2 = 31 as TeamId
            const localProjectId1 = 30 as ProjectId
            const localProjectId2 = 31 as ProjectId

            await insertTestTeam(postgres, localTeamId1)
            await insertTestTeam(postgres, localTeamId2)

            // Insert group types for both teams
            await repository.insertGroupType(localTeamId1, localProjectId1, 'company', 0)
            await repository.insertGroupType(localTeamId2, localProjectId2, 'organization', 0)

            const result = await repository.fetchGroupTypesByTeamIds([localTeamId1, localTeamId2])

            expect(result).toEqual({
                [localTeamId1]: [{ group_type: 'company', group_type_index: 0 }],
                [localTeamId2]: [{ group_type: 'organization', group_type_index: 0 }],
            })
        })

        it('should read from primary only (not secondary)', async () => {
            // Insert directly to primary only using postgres client
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_grouptypemapping (team_id, project_id, group_type, group_type_index, created_at) VALUES ($1, $2, $3, $4, $5)',
                [teamId, projectId, 'primary_only', 0, new Date()],
                'insert-primary-only'
            )

            const result = await repository.fetchGroupTypesByTeamIds([teamId])

            expect(result).toEqual({
                [teamId]: [{ group_type: 'primary_only', group_type_index: 0 }],
            })

            // Verify secondary has no data
            const secondaryResult = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1',
                [teamId],
                'test-secondary-check'
            )
            expect(secondaryResult.rows).toHaveLength(0)
        })
    })

    describe('fetchGroupsByKeys() 2PC tests', () => {
        const teamId = 1 as TeamId
        const groupTypeIndex = 0 as GroupTypeIndex
        const groupKey = 'test-group'
        const groupProperties = { name: 'Test Group', type: 'company' }
        const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

        beforeEach(async () => {
            // Setup group type
            await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)
        })

        it('should return empty array for empty inputs', async () => {
            expect(await repository.fetchGroupsByKeys([], [], [])).toEqual([])
            expect(await repository.fetchGroupsByKeys([teamId], [], [])).toEqual([])
        })

        it('should fetch from primary repository only', async () => {
            // Insert group using dual-write repository (writes to both)
            await repository.insertGroup(teamId, groupTypeIndex, groupKey, groupProperties, createdAt, {}, {})

            const result = await repository.fetchGroupsByKeys([teamId], [groupTypeIndex], [groupKey])

            expect(result).toHaveLength(1)
            expect(result[0]).toEqual({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: groupProperties,
            })
        })

        it('should handle multiple groups', async () => {
            const group1Props = { name: 'Group 1' }
            const group2Props = { name: 'Group 2' }

            // Insert multiple groups
            await repository.insertGroup(teamId, groupTypeIndex, 'group1', group1Props, createdAt, {}, {})
            await repository.insertGroup(teamId, groupTypeIndex, 'group2', group2Props, createdAt, {}, {})

            const result = await repository.fetchGroupsByKeys(
                [teamId, teamId],
                [groupTypeIndex, groupTypeIndex],
                ['group1', 'group2']
            )

            expect(result).toHaveLength(2)
            expect(result).toEqual(
                expect.arrayContaining([
                    {
                        team_id: teamId,
                        group_type_index: groupTypeIndex,
                        group_key: 'group1',
                        group_properties: group1Props,
                    },
                    {
                        team_id: teamId,
                        group_type_index: groupTypeIndex,
                        group_key: 'group2',
                        group_properties: group2Props,
                    },
                ])
            )
        })

        it('should read from primary only (not secondary)', async () => {
            // Insert directly to primary only using postgres client
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `INSERT INTO posthog_group (team_id, group_type_index, group_key, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
                [teamId, groupTypeIndex, 'primary_only', { name: 'Primary Only' }, createdAt.toISO(), '{}', '{}', 1],
                'insert-group-primary-only'
            )

            const result = await repository.fetchGroupsByKeys([teamId], [groupTypeIndex], ['primary_only'])

            expect(result).toHaveLength(1)
            expect(result[0]).toEqual({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: 'primary_only',
                group_properties: { name: 'Primary Only' },
            })

            // Verify secondary has no data
            const secondaryResult = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'primary_only'],
                'test-secondary-check'
            )
            expect(secondaryResult.rows).toHaveLength(0)
        })

        it('should handle non-existent groups', async () => {
            const result = await repository.fetchGroupsByKeys([teamId], [groupTypeIndex], ['non-existent'])

            expect(result).toEqual([])
        })
    })
})
