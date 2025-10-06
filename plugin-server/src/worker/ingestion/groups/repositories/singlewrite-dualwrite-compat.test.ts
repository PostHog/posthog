import { DateTime } from 'luxon'

import { insertRow, resetTestDatabase } from '../../../../../tests/helpers/sql'
import { GroupTypeIndex, Hub, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '../../../../types'
import { closeHub, createHub } from '../../../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { RaceConditionError, UUIDT } from '../../../../utils/utils'
import { PostgresDualWriteGroupRepository } from './postgres-dualwrite-group-repository'
import { PostgresGroupRepository } from './postgres-group-repository'

jest.mock('../../../../utils/logger')

describe('Groups Single Write - Dual Write Compatibility', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let dualWriteRepository: PostgresDualWriteGroupRepository
    let singleWriteRepository: PostgresGroupRepository

    const TEST_TIMESTAMP = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

    async function setupMigrationDbForGroups(migrationPostgres: PostgresRouter): Promise<void> {
        await migrationPostgres.query(
            PostgresUse.PERSONS_WRITE,
            `DROP TABLE IF EXISTS posthog_group CASCADE`,
            [],
            'drop-group-table'
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

    async function createGroupsInBothRepos(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        properties: Record<string, any> = { name: 'Test Group' },
        singleGroupKey: string = 'single-group',
        dualGroupKey: string = 'dual-group',
        createdAt: DateTime = TEST_TIMESTAMP
    ) {
        const propertiesLastUpdatedAt: PropertiesLastUpdatedAt = {}
        const propertiesLastOperation: PropertiesLastOperation = {}

        const [singleVersion, dualVersion] = await Promise.all([
            singleWriteRepository.insertGroup(
                teamId,
                groupTypeIndex,
                singleGroupKey,
                properties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            ),
            dualWriteRepository.insertGroup(
                teamId,
                groupTypeIndex,
                dualGroupKey,
                properties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            ),
        ])

        return { singleVersion, dualVersion }
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        migrationPostgres = hub.db.postgresPersonMigration
        await setupMigrationDbForGroups(migrationPostgres)

        dualWriteRepository = new PostgresDualWriteGroupRepository(postgres, migrationPostgres, {
            comparisonEnabled: true,
        })
        singleWriteRepository = new PostgresGroupRepository(postgres)

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

    describe('insertGroup() compatibility between single and dual write', () => {
        it('happy path insertGroup()', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupProperties = { name: 'Bob Group', type: 'company' }
            const createdAt = TEST_TIMESTAMP
            const propertiesLastUpdatedAt: PropertiesLastUpdatedAt = {}
            const propertiesLastOperation: PropertiesLastOperation = {}

            const singleVersion = await singleWriteRepository.insertGroup(
                teamId,
                groupTypeIndex,
                'single-happy',
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            const dualVersion = await dualWriteRepository.insertGroup(
                teamId,
                groupTypeIndex,
                'dual-happy',
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(singleVersion).toBe(1)
            expect(dualVersion).toBe(1)

            const primaryGroup = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties, version FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-happy'],
                'verify-primary-insert'
            )
            const secondaryGroup = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties, version FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-happy'],
                'verify-secondary-insert'
            )
            expect(primaryGroup.rows[0].group_properties).toEqual(groupProperties)
            expect(secondaryGroup.rows[0].group_properties).toEqual(groupProperties)
            expect(Number(primaryGroup.rows[0].version)).toBe(1)
            expect(Number(secondaryGroup.rows[0].version)).toBe(1)
        })

        it('handles race condition errors consistently', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupProperties = { name: 'Race Test' }
            const createdAt = TEST_TIMESTAMP

            // Insert in single write
            await singleWriteRepository.insertGroup(
                teamId,
                groupTypeIndex,
                'single-race',
                groupProperties,
                createdAt,
                {},
                {}
            )

            await expect(
                singleWriteRepository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'single-race',
                    groupProperties,
                    createdAt,
                    {},
                    {}
                )
            ).rejects.toThrow(RaceConditionError)

            await dualWriteRepository.insertGroup(
                teamId,
                groupTypeIndex,
                'dual-race',
                groupProperties,
                createdAt,
                {},
                {}
            )

            await expect(
                dualWriteRepository.insertGroup(teamId, groupTypeIndex, 'dual-race', groupProperties, createdAt, {}, {})
            ).rejects.toThrow(RaceConditionError)
        })
    })

    describe('updateGroup() compatibility between single and dual write', () => {
        it('happy path updateGroup()', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const initialProperties = { name: 'Initial' }
            const updatedProperties = { name: 'Updated', new_field: 'value' }
            const createdAt = TEST_TIMESTAMP

            await createGroupsInBothRepos(
                teamId,
                groupTypeIndex,
                initialProperties,
                'single-update',
                'dual-update',
                createdAt
            )

            const [singleVersion, dualVersion] = await Promise.all([
                singleWriteRepository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'single-update',
                    updatedProperties,
                    createdAt,
                    {},
                    {},
                    'single-update-tag'
                ),
                dualWriteRepository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'dual-update',
                    updatedProperties,
                    createdAt,
                    {},
                    {},
                    'dual-update-tag'
                ),
            ])

            expect(singleVersion).toBe(2)
            expect(dualVersion).toBe(2)

            const dualGroup = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-update'],
                'verify-dual-update'
            )
            const secondaryGroup = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-update'],
                'verify-secondary-update'
            )

            expect(dualGroup.rows[0].group_properties).toEqual(updatedProperties)
            expect(secondaryGroup.rows[0].group_properties).toEqual(updatedProperties)
        })

        it('returns undefined for non-existent groups', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupProperties = { name: 'Should not update' }
            const createdAt = TEST_TIMESTAMP

            const [singleResult, dualResult] = await Promise.all([
                singleWriteRepository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'non-existent-single',
                    groupProperties,
                    createdAt,
                    {},
                    {},
                    'test-tag'
                ),
                dualWriteRepository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'non-existent-dual',
                    groupProperties,
                    createdAt,
                    {},
                    {},
                    'test-tag'
                ),
            ])

            expect(singleResult).toBeUndefined()
            expect(dualResult).toBeUndefined()
        })
    })

    describe('updateGroupOptimistically() compatibility', () => {
        it('successful optimistic update', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const initialProperties = { name: 'Initial' }
            const updatedProperties = { name: 'Optimistically Updated' }
            const createdAt = TEST_TIMESTAMP

            await createGroupsInBothRepos(
                teamId,
                groupTypeIndex,
                initialProperties,
                'single-optimistic',
                'dual-optimistic',
                createdAt
            )

            const [singleVersion, dualVersion] = await Promise.all([
                singleWriteRepository.updateGroupOptimistically(
                    teamId,
                    groupTypeIndex,
                    'single-optimistic',
                    1,
                    updatedProperties,
                    createdAt,
                    {},
                    {}
                ),
                dualWriteRepository.updateGroupOptimistically(
                    teamId,
                    groupTypeIndex,
                    'dual-optimistic',
                    1,
                    updatedProperties,
                    createdAt,
                    {},
                    {}
                ),
            ])

            expect(singleVersion).toBe(2)
            expect(dualVersion).toBe(2)

            const primaryResult = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties, version FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-optimistic'],
                'verify-primary-optimistic'
            )
            const secondaryResult = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties, version FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-optimistic'],
                'verify-secondary-optimistic'
            )
            expect(primaryResult.rows[0].group_properties).toEqual(updatedProperties)
            expect(secondaryResult.rows[0].group_properties).toEqual(updatedProperties)
            expect(Number(primaryResult.rows[0].version)).toBe(2)
            expect(Number(secondaryResult.rows[0].version)).toBe(2)
        })

        it('returns undefined on version mismatch', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const initialProperties = { name: 'Initial' }
            const updatedProperties = { name: 'Should not update' }
            const createdAt = TEST_TIMESTAMP

            await createGroupsInBothRepos(
                teamId,
                groupTypeIndex,
                initialProperties,
                'single-mismatch',
                'dual-mismatch',
                createdAt
            )

            const [singleResult, dualResult] = await Promise.all([
                singleWriteRepository.updateGroupOptimistically(
                    teamId,
                    groupTypeIndex,
                    'single-mismatch',
                    999,
                    updatedProperties,
                    createdAt,
                    {},
                    {}
                ),
                dualWriteRepository.updateGroupOptimistically(
                    teamId,
                    groupTypeIndex,
                    'dual-mismatch',
                    999,
                    updatedProperties,
                    createdAt,
                    {},
                    {}
                ),
            ])

            expect(singleResult).toBeUndefined()
            expect(dualResult).toBeUndefined()
        })
    })

    describe('fetchGroup() compatibility', () => {
        it('fetches groups consistently', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupProperties = { name: 'Fetch Test', type: 'organization' }
            const createdAt = TEST_TIMESTAMP

            await createGroupsInBothRepos(
                teamId,
                groupTypeIndex,
                groupProperties,
                'single-fetch',
                'dual-fetch',
                createdAt
            )

            const [singleGroup, dualGroup] = await Promise.all([
                singleWriteRepository.fetchGroup(teamId, groupTypeIndex, 'single-fetch'),
                dualWriteRepository.fetchGroup(teamId, groupTypeIndex, 'dual-fetch'),
            ])

            expect(singleGroup).toBeDefined()
            expect(dualGroup).toBeDefined()
            expect(singleGroup?.group_properties).toEqual(groupProperties)
            expect(dualGroup?.group_properties).toEqual(groupProperties)
            expect(singleGroup?.version).toBe(1)
            expect(dualGroup?.version).toBe(1)
        })

        it('returns undefined for non-existent groups', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex

            const [singleGroup, dualGroup] = await Promise.all([
                singleWriteRepository.fetchGroup(teamId, groupTypeIndex, 'non-existent-single'),
                dualWriteRepository.fetchGroup(teamId, groupTypeIndex, 'non-existent-dual'),
            ])

            expect(singleGroup).toBeUndefined()
            expect(dualGroup).toBeUndefined()
        })

        it('fetches with forUpdate lock', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupProperties = { name: 'Lock Test' }
            const createdAt = TEST_TIMESTAMP

            await createGroupsInBothRepos(
                teamId,
                groupTypeIndex,
                groupProperties,
                'single-lock',
                'dual-lock',
                createdAt
            )

            const [singleGroup, dualGroup] = await Promise.all([
                singleWriteRepository.fetchGroup(teamId, groupTypeIndex, 'single-lock', { forUpdate: true }),
                dualWriteRepository.fetchGroup(teamId, groupTypeIndex, 'dual-lock', { forUpdate: true }),
            ])

            expect(singleGroup).toBeDefined()
            expect(dualGroup).toBeDefined()
            expect(singleGroup?.group_properties).toEqual(groupProperties)
            expect(dualGroup?.group_properties).toEqual(groupProperties)
        })
    })

    describe('inTransaction() compatibility', () => {
        it('executes transactions consistently', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = TEST_TIMESTAMP

            const singleResult = await singleWriteRepository.inTransaction('single-tx', async (tx) => {
                const version1 = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'single-tx-1',
                    { name: 'TX Group 1' },
                    createdAt,
                    {},
                    {}
                )

                const version2 = await tx.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'single-tx-1',
                    { name: 'TX Group 1 Updated' },
                    createdAt,
                    {},
                    {},
                    'tx-update'
                )

                return { version1, version2 }
            })

            const dualResult = await dualWriteRepository.inTransaction('dual-tx', async (tx) => {
                const version1 = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'dual-tx-1',
                    { name: 'TX Group 1' },
                    createdAt,
                    {},
                    {}
                )

                const version2 = await tx.updateGroup(
                    teamId,
                    groupTypeIndex,
                    'dual-tx-1',
                    { name: 'TX Group 1 Updated' },
                    createdAt,
                    {},
                    {},
                    'tx-update'
                )

                return { version1, version2 }
            })

            expect(singleResult.version1).toBe(1)
            expect(singleResult.version2).toBe(2)
            expect(dualResult.version1).toBe(1)
            expect(dualResult.version2).toBe(2)

            const primaryTx = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties, version FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-tx-1'],
                'verify-primary-tx'
            )
            const secondaryTx = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT group_properties, version FROM posthog_group WHERE team_id = $1 AND group_key = $2',
                [teamId, 'dual-tx-1'],
                'verify-secondary-tx'
            )
            expect(primaryTx.rows[0].group_properties).toEqual({ name: 'TX Group 1 Updated' })
            expect(secondaryTx.rows[0].group_properties).toEqual({ name: 'TX Group 1 Updated' })
            expect(Number(primaryTx.rows[0].version)).toBe(2)
            expect(Number(secondaryTx.rows[0].version)).toBe(2)
        })

        it('rollback behavior is consistent', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const createdAt = TEST_TIMESTAMP

            await expect(
                singleWriteRepository.inTransaction('single-rollback', async (tx) => {
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'single-rollback-1',
                        { name: 'Will Rollback' },
                        createdAt,
                        {},
                        {}
                    )
                    throw new Error('Intentional rollback')
                })
            ).rejects.toThrow('Intentional rollback')

            await expect(
                dualWriteRepository.inTransaction('dual-rollback', async (tx) => {
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        'dual-rollback-1',
                        { name: 'Will Rollback' },
                        createdAt,
                        {},
                        {}
                    )
                    throw new Error('Intentional rollback')
                })
            ).rejects.toThrow('Intentional rollback')

            const singleCheck = await singleWriteRepository.fetchGroup(teamId, groupTypeIndex, 'single-rollback-1')
            const dualCheck = await dualWriteRepository.fetchGroup(teamId, groupTypeIndex, 'dual-rollback-1')

            expect(singleCheck).toBeUndefined()
            expect(dualCheck).toBeUndefined()
        })
    })

    describe('Error handling consistency', () => {
        it('handles database errors consistently', async () => {
            const teamId = 1 as TeamId
            const groupTypeIndex = 0 as GroupTypeIndex
            const groupProperties = { name: 'Error Test' }
            const createdAt = TEST_TIMESTAMP

            const singleSpy = jest
                .spyOn((singleWriteRepository as any).postgres, 'query')
                .mockRejectedValueOnce(new Error('Database connection lost'))

            const dualSpy = jest
                .spyOn((dualWriteRepository as any).primaryRepo, 'insertGroup')
                .mockRejectedValueOnce(new Error('Database connection lost'))

            await expect(
                singleWriteRepository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'single-error',
                    groupProperties,
                    createdAt,
                    {},
                    {}
                )
            ).rejects.toThrow('Database connection lost')

            await expect(
                dualWriteRepository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    'dual-error',
                    groupProperties,
                    createdAt,
                    {},
                    {}
                )
            ).rejects.toThrow('Database connection lost')

            singleSpy.mockRestore()
            dualSpy.mockRestore()
        })
    })
})
