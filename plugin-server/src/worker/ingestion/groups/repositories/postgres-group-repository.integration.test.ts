import { DateTime } from 'luxon'

import { insertRow, resetTestDatabase } from '../../../../../tests/helpers/sql'
import {
    GroupTypeIndex,
    Hub,
    ProjectId,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    PropertyUpdateOperation,
    TeamId,
} from '../../../../types'
import { closeHub, createHub } from '../../../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { UUIDT } from '../../../../utils/utils'
import { PostgresGroupRepository } from './postgres-group-repository'

describe('PostgresGroupRepository Integration', () => {
    let hub: Hub
    let repository: PostgresGroupRepository
    let postgres: PostgresRouter

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        repository = new PostgresGroupRepository(postgres)

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.db.redisPool.release(redis)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const teamId = 1 as TeamId
    const groupTypeIndex = 0 as GroupTypeIndex
    const groupKey = 'test-group-key'
    const groupProperties = { name: 'Test Group', type: 'company' }
    const createdAt = DateTime.fromISO('2023-01-01T00:00:00Z').toUTC()
    const propertiesLastUpdatedAt: PropertiesLastUpdatedAt = {}
    const propertiesLastOperation: PropertiesLastOperation = {}

    const insertTestTeam = async (teamId: number) => {
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
            app_urls: [],
            event_names: [],
            event_names_with_usage: [],
            event_properties: [],
            event_properties_with_usage: [],
            event_properties_numerical: [],
            session_recording_retention_period: '30d',
        })
    }

    const insertTestGroup = async (overrides: Record<string, any> = {}) => {
        const finalTeamId = overrides.team_id || teamId

        await insertRow(postgres, 'posthog_group', {
            team_id: finalTeamId,
            group_type_index: groupTypeIndex,
            group_key: groupKey,
            group_properties: JSON.stringify(groupProperties),
            properties_last_updated_at: JSON.stringify(propertiesLastUpdatedAt),
            properties_last_operation: JSON.stringify(propertiesLastOperation),
            created_at: createdAt.toISO(),
            version: overrides.version || 1,
            ...overrides,
        })
    }

    describe('fetchGroup', () => {
        it('should fetch a group successfully', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const result = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)

            expect(result).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: groupProperties,
                properties_last_updated_at: propertiesLastUpdatedAt,
                properties_last_operation: propertiesLastOperation,
                created_at: createdAt,
                version: 1,
            })
        })

        it('should return undefined when group not found', async () => {
            const result = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)

            expect(result).toBeUndefined()
        })

        it('should handle forUpdate option', async () => {
            const mockQuery = jest.spyOn(postgres, 'query').mockResolvedValue({
                rows: [
                    {
                        team_id: teamId,
                        group_type_index: groupTypeIndex,
                        group_key: groupKey,
                        group_properties: JSON.stringify(groupProperties),
                        properties_last_updated_at: JSON.stringify(propertiesLastUpdatedAt),
                        properties_last_operation: JSON.stringify(propertiesLastOperation),
                        created_at: createdAt.toISO(),
                        version: 1,
                    },
                ],
            } as any)

            await repository.fetchGroup(teamId, groupTypeIndex, groupKey, { forUpdate: true })

            expect(mockQuery).toHaveBeenCalledWith(
                PostgresUse.PERSONS_WRITE,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3 FOR UPDATE',
                [teamId, groupTypeIndex, groupKey],
                'fetchGroup'
            )

            mockQuery.mockRestore()
        })

        it('should handle useReadReplica option', async () => {
            const mockQuery = jest.spyOn(postgres, 'query').mockResolvedValue({
                rows: [
                    {
                        team_id: teamId,
                        group_type_index: groupTypeIndex,
                        group_key: groupKey,
                        group_properties: JSON.stringify(groupProperties),
                        properties_last_updated_at: JSON.stringify(propertiesLastUpdatedAt),
                        properties_last_operation: JSON.stringify(propertiesLastOperation),
                        created_at: createdAt.toISO(),
                        version: 1,
                    },
                ],
            } as any)

            await repository.fetchGroup(teamId, groupTypeIndex, groupKey, { useReadReplica: true })

            expect(mockQuery).toHaveBeenCalledWith(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3',
                [teamId, groupTypeIndex, groupKey],
                'fetchGroup'
            )

            mockQuery.mockRestore()
        })

        it('should throw error when both forUpdate and useReadReplica are enabled', async () => {
            await expect(
                repository.fetchGroup(teamId, groupTypeIndex, groupKey, { forUpdate: true, useReadReplica: true })
            ).rejects.toThrow("can't enable both forUpdate and useReadReplica in fetchGroup")
        })

        it('should handle different group types and keys', async () => {
            const group1Key = 'company-group-1'
            const group1TypeIndex = 0 as GroupTypeIndex
            const group1TeamId = 10 as TeamId
            const group1ProjectId = 101
            const group1Properties = { name: 'Company A', industry: 'tech' }
            const group1CreatedAt = DateTime.fromISO('2023-01-01T00:00:00Z').toUTC()

            const group2Key = 'organization-group-2'
            const group2TypeIndex = 1 as GroupTypeIndex
            const group2TeamId = 20 as TeamId
            const group2ProjectId = 102
            const group2Properties = { name: 'Organization B', sector: 'finance' }
            const group2CreatedAt = DateTime.fromISO('2023-02-01T00:00:00Z').toUTC()

            // Insert first group with its own team/project
            await insertRow(postgres, 'posthog_project', {
                id: group1ProjectId,
                organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
                name: `Test Project ${group1ProjectId}`,
                created_at: new Date().toISOString(),
            })
            await insertRow(postgres, 'posthog_team', {
                id: group1TeamId,
                name: `Test Team ${group1TeamId}`,
                organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
                project_id: group1ProjectId,
                uuid: new UUIDT().toString(),
                api_token: `test-api-token-${group1TeamId}`,
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
                app_urls: [],
                event_names: [],
                event_names_with_usage: [],
                event_properties: [],
                event_properties_with_usage: [],
                event_properties_numerical: [],
                session_recording_retention_period: '30d',
            })
            await insertRow(postgres, 'posthog_group', {
                team_id: group1TeamId,
                group_type_index: group1TypeIndex,
                group_key: group1Key,
                group_properties: JSON.stringify(group1Properties),
                properties_last_updated_at: JSON.stringify(propertiesLastUpdatedAt),
                properties_last_operation: JSON.stringify(propertiesLastOperation),
                created_at: group1CreatedAt.toISO(),
                version: 1,
            })

            // Insert second group with its own team/project
            await insertRow(postgres, 'posthog_project', {
                id: group2ProjectId,
                organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
                name: `Test Project ${group2ProjectId}`,
                created_at: new Date().toISOString(),
            })
            await insertRow(postgres, 'posthog_team', {
                id: group2TeamId,
                name: `Test Team ${group2TeamId}`,
                organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
                project_id: group2ProjectId,
                uuid: new UUIDT().toString(),
                api_token: `test-api-token-${group2TeamId}`,
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
                app_urls: [],
                event_names: [],
                event_names_with_usage: [],
                event_properties: [],
                event_properties_with_usage: [],
                event_properties_numerical: [],
                session_recording_retention_period: '30d',
            })
            await insertRow(postgres, 'posthog_group', {
                team_id: group2TeamId,
                group_type_index: group2TypeIndex,
                group_key: group2Key,
                group_properties: JSON.stringify(group2Properties),
                properties_last_updated_at: JSON.stringify(propertiesLastUpdatedAt),
                properties_last_operation: JSON.stringify(propertiesLastOperation),
                created_at: group2CreatedAt.toISO(),
                version: 2,
            })

            // Fetch both groups
            const result1 = await repository.fetchGroup(group1TeamId, group1TypeIndex, group1Key)
            const result2 = await repository.fetchGroup(group2TeamId, group2TypeIndex, group2Key)

            // Verify first group properties
            expect(result1).toMatchObject({
                team_id: group1TeamId,
                group_type_index: group1TypeIndex,
                group_key: group1Key,
                group_properties: group1Properties,
                properties_last_updated_at: propertiesLastUpdatedAt,
                properties_last_operation: propertiesLastOperation,
                created_at: group1CreatedAt,
                version: 1,
            })

            // Verify second group properties
            expect(result2).toMatchObject({
                team_id: group2TeamId,
                group_type_index: group2TypeIndex,
                group_key: group2Key,
                group_properties: group2Properties,
                properties_last_updated_at: propertiesLastUpdatedAt,
                properties_last_operation: propertiesLastOperation,
                created_at: group2CreatedAt,
                version: 2,
            })

            // Verify they are different
            expect(result1?.group_key).not.toBe(result2?.group_key)
            expect(result1?.group_type_index).not.toBe(result2?.group_type_index)
            expect(result1?.team_id).not.toBe(result2?.team_id)
        })
    })

    describe('insertGroup', () => {
        it('should insert a group successfully', async () => {
            await insertTestTeam(teamId)

            const result = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            // Verify the group was actually inserted
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: groupProperties,
                properties_last_updated_at: propertiesLastUpdatedAt,
                properties_last_operation: propertiesLastOperation,
                created_at: createdAt,
                version: 1,
            })
        })

        it('should handle duplicate insert with ON CONFLICT DO NOTHING', async () => {
            await insertTestTeam(teamId)

            // First insert should succeed
            const result1 = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )
            expect(result1).toBe(1)

            // Second insert should throw RaceConditionError due to ON CONFLICT DO NOTHING
            await expect(
                repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation
                )
            ).rejects.toThrow('Parallel posthog_group inserts, retry')
        })

        it('should handle different group properties', async () => {
            await insertTestTeam(teamId)

            const customProperties = { name: 'Custom Group', type: 'organization', size: 'large' }
            const customCreatedAt = DateTime.fromISO('2023-03-01T00:00:00Z').toUTC()
            const customPropertiesLastUpdatedAt = { name: '2023-03-01T00:00:00Z' }
            const customPropertiesLastOperation = { name: PropertyUpdateOperation.Set }

            const result = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                customProperties,
                customCreatedAt,
                customPropertiesLastUpdatedAt,
                customPropertiesLastOperation
            )

            expect(result).toBe(1)

            // Verify the group was inserted with custom properties
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: customProperties,
                properties_last_updated_at: customPropertiesLastUpdatedAt,
                properties_last_operation: customPropertiesLastOperation,
                created_at: customCreatedAt,
                version: 1,
            })
        })

        it('should handle insertGroup with transaction', async () => {
            await insertTestTeam(teamId)

            const result = await repository.inTransaction('insert group with transaction', async (tx) => {
                return await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation
                )
            })

            expect(result).toBe(1)

            // Verify the group was actually inserted
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: groupProperties,
                properties_last_updated_at: propertiesLastUpdatedAt,
                properties_last_operation: propertiesLastOperation,
                created_at: createdAt,
                version: 1,
            })
        })

        it('should handle insertGroup with raw transaction', async () => {
            await insertTestTeam(teamId)

            const result = await repository.inRawTransaction('insert group with raw transaction', async (tx) => {
                return await repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    tx
                )
            })

            expect(result).toBe(1)

            // Verify the group was actually inserted
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: groupProperties,
                properties_last_updated_at: propertiesLastUpdatedAt,
                properties_last_operation: propertiesLastOperation,
                created_at: createdAt,
                version: 1,
            })
        })
    })

    describe('updateGroup', () => {
        it('should update a group successfully', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const updatedProperties = { name: 'Updated Group', type: 'company', size: 'large' }
            const updatedCreatedAt = DateTime.fromISO('2023-02-01T00:00:00Z').toUTC()
            const updatedPropertiesLastUpdatedAt = { name: '2023-02-01T00:00:00Z' }
            const updatedPropertiesLastOperation = { name: PropertyUpdateOperation.Set }

            const result = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                updatedProperties,
                updatedCreatedAt,
                updatedPropertiesLastUpdatedAt,
                updatedPropertiesLastOperation,
                'test-update'
            )

            expect(result).toBe(2) // Version should be incremented from 1 to 2

            // Verify the group was actually updated
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: updatedProperties,
                properties_last_updated_at: updatedPropertiesLastUpdatedAt,
                properties_last_operation: updatedPropertiesLastOperation,
                created_at: updatedCreatedAt,
                version: 2,
            })
        })

        it('should return undefined when group not found', async () => {
            await insertTestTeam(teamId)

            const result = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                'test-update'
            )

            expect(result).toBeUndefined()
        })

        it('should handle multiple updates and version increments', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            // First update
            const result1 = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                { name: 'First Update' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                'first-update'
            )
            expect(result1).toBe(2)

            // Second update
            const result2 = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                { name: 'Second Update' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                'second-update'
            )
            expect(result2).toBe(3)

            // Third update
            const result3 = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                { name: 'Third Update' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                'third-update'
            )
            expect(result3).toBe(4)

            // Verify final state
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.version).toBe(4)
            expect(fetchedGroup?.group_properties).toMatchObject({ name: 'Third Update' })
        })

        it('should handle group with null version', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup({ version: 0 })

            const result = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                'test-update'
            )

            expect(result).toBe(1) // Should increment from 0 to 1
        })

        it('should handle updateGroup with transaction', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const updatedProperties = { name: 'Transaction Update', type: 'company' }
            const updatedCreatedAt = DateTime.fromISO('2023-03-01T00:00:00Z').toUTC()
            const updatedPropertiesLastUpdatedAt = { name: '2023-03-01T00:00:00Z' }
            const updatedPropertiesLastOperation = { name: PropertyUpdateOperation.Set }

            const result = await repository.inTransaction('update group with transaction', async (tx) => {
                return await tx.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    updatedProperties,
                    updatedCreatedAt,
                    updatedPropertiesLastUpdatedAt,
                    updatedPropertiesLastOperation,
                    'transaction-update'
                )
            })

            expect(result).toBe(2)

            // Verify the group was actually updated
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: updatedProperties,
                properties_last_updated_at: updatedPropertiesLastUpdatedAt,
                properties_last_operation: updatedPropertiesLastOperation,
                created_at: updatedCreatedAt,
                version: 2,
            })
        })

        it('should handle updateGroup with raw transaction', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const updatedProperties = { name: 'Raw Transaction Update', type: 'company' }
            const updatedCreatedAt = DateTime.fromISO('2023-04-01T00:00:00Z').toUTC()
            const updatedPropertiesLastUpdatedAt = { name: '2023-04-01T00:00:00Z' }
            const updatedPropertiesLastOperation = { name: PropertyUpdateOperation.Set }

            const result = await repository.inRawTransaction('update group with raw transaction', async (tx) => {
                return await repository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    updatedProperties,
                    updatedCreatedAt,
                    updatedPropertiesLastUpdatedAt,
                    updatedPropertiesLastOperation,
                    'raw-transaction-update',
                    tx
                )
            })

            expect(result).toBe(2)

            // Verify the group was actually updated
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: updatedProperties,
                properties_last_updated_at: updatedPropertiesLastUpdatedAt,
                properties_last_operation: updatedPropertiesLastOperation,
                created_at: updatedCreatedAt,
                version: 2,
            })
        })
    })

    describe('updateGroupOptimistically', () => {
        it('should update a group successfully when version matches', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const updatedProperties = { name: 'Optimistic Update', type: 'company', size: 'large' }
            const updatedCreatedAt = DateTime.fromISO('2023-05-01T00:00:00Z').toUTC()
            const updatedPropertiesLastUpdatedAt = { name: '2023-05-01T00:00:00Z' }
            const updatedPropertiesLastOperation = { name: PropertyUpdateOperation.Set }

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                1, // expectedVersion - should match current version
                updatedProperties,
                updatedCreatedAt,
                updatedPropertiesLastUpdatedAt,
                updatedPropertiesLastOperation
            )

            expect(result).toBe(2) // Version should be incremented from 1 to 2

            // Verify the group was actually updated
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: updatedProperties,
                properties_last_updated_at: updatedPropertiesLastUpdatedAt,
                properties_last_operation: updatedPropertiesLastOperation,
                created_at: updatedCreatedAt,
                version: 2,
            })
        })

        it('should return undefined when version does not match', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                2, // expectedVersion - does not match current version (1)
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBeUndefined()

            // Verify the group was NOT updated
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.version).toBe(1) // Version should remain unchanged
            expect(fetchedGroup?.group_properties).toMatchObject(groupProperties) // Properties should remain unchanged
        })

        it('should return undefined when group not found', async () => {
            await insertTestTeam(teamId)

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                1, // expectedVersion
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBeUndefined()
        })

        it('should handle optimistic updates with version increments', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            // First optimistic update
            const result1 = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                1, // expectedVersion
                { name: 'First Optimistic Update' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )
            expect(result1).toBe(2)

            // Second optimistic update
            const result2 = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                2, // expectedVersion
                { name: 'Second Optimistic Update' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )
            expect(result2).toBe(3)

            // Third optimistic update
            const result3 = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                3, // expectedVersion
                { name: 'Third Optimistic Update' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )
            expect(result3).toBe(4)

            // Verify final state
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.version).toBe(4)
            expect(fetchedGroup?.group_properties).toMatchObject({ name: 'Third Optimistic Update' })
        })

        it('should handle group with null version', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup({ version: 0 })

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                0, // expectedVersion - should match current version (0)
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1) // Should increment from 0 to 1
        })

        it('should fail optimistic update when version is wrong for null version group', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup({ version: 0 })

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                1, // expectedVersion - wrong for current version (0)
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBeUndefined()

            // Verify the group was NOT updated
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.version).toBe(0) // Version should remain unchanged
        })
    })

    describe('inTransaction', () => {
        it('should execute operations within a transaction', async () => {
            await insertTestTeam(teamId)

            const result = await repository.inTransaction('test transaction', async (tx) => {
                // Insert a group within transaction
                const insertResult = await tx.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation
                )

                // Fetch the group within transaction
                const fetchedGroup = await tx.fetchGroup(teamId, groupTypeIndex, groupKey)

                // Update the group within transaction
                const updateResult = await tx.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    { name: 'Updated in Transaction' },
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    'transaction-update'
                )

                return {
                    insertResult,
                    fetchedGroup,
                    updateResult,
                }
            })

            expect(result.insertResult).toBe(1)
            expect(result.fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: groupProperties,
                version: 1,
            })
            expect(result.updateResult).toBe(2)

            // Verify the final state outside transaction
            const finalGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(finalGroup?.version).toBe(2)
            expect(finalGroup?.group_properties).toMatchObject({ name: 'Updated in Transaction' })
        })

        it('should rollback transaction on error', async () => {
            await insertTestTeam(teamId)

            // Try to execute a transaction that will fail
            await expect(
                repository.inTransaction('failing transaction', async (tx) => {
                    // Insert a group
                    await tx.insertGroup(
                        teamId,
                        groupTypeIndex,
                        groupKey,
                        groupProperties,
                        createdAt,
                        propertiesLastUpdatedAt,
                        propertiesLastOperation
                    )

                    // This should cause the transaction to rollback
                    throw new Error('Simulated transaction failure')
                })
            ).rejects.toThrow('Simulated transaction failure')

            // Verify the group was not inserted (transaction rolled back)
            const group = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(group).toBeUndefined()
        })
    })

    describe('inRawTransaction', () => {
        it('should execute operations within a raw transaction', async () => {
            await insertTestTeam(teamId)

            const result = await repository.inRawTransaction('test raw transaction', async (tx) => {
                // Insert a group within raw transaction
                const insertResult = await repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    tx
                )

                // Fetch the group within raw transaction
                const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey, undefined, tx)

                // Update the group within raw transaction
                const updateResult = await repository.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    { name: 'Updated in Raw Transaction' },
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    'raw-transaction-update',
                    tx
                )

                return {
                    insertResult,
                    fetchedGroup,
                    updateResult,
                }
            })

            expect(result.insertResult).toBe(1)
            expect(result.fetchedGroup).toMatchObject({
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: groupProperties,
                version: 1,
            })
            expect(result.updateResult).toBe(2)

            // Verify the final state outside transaction
            const finalGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(finalGroup?.version).toBe(2)
            expect(finalGroup?.group_properties).toMatchObject({ name: 'Updated in Raw Transaction' })
        })

        it('should rollback raw transaction on error', async () => {
            await insertTestTeam(teamId)

            // Try to execute a raw transaction that will fail
            await expect(
                repository.inRawTransaction('failing raw transaction', async (tx) => {
                    // Insert a group
                    await repository.insertGroup(
                        teamId,
                        groupTypeIndex,
                        groupKey,
                        groupProperties,
                        createdAt,
                        propertiesLastUpdatedAt,
                        propertiesLastOperation,
                        tx
                    )

                    // This should cause the transaction to rollback
                    throw new Error('Simulated raw transaction failure')
                })
            ).rejects.toThrow('Simulated raw transaction failure')

            // Verify the group was not inserted (transaction rolled back)
            const group = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(group).toBeUndefined()
        })
    })

    describe('error handling', () => {
        it('should handle database connection errors gracefully', async () => {
            // Mock postgres to simulate connection error
            const mockPostgres = {
                query: jest.fn().mockRejectedValue(new Error('Connection terminated unexpectedly')),
            }

            const repositoryWithMockPostgres = new PostgresGroupRepository(mockPostgres as any)

            await expect(repositoryWithMockPostgres.fetchGroup(teamId, groupTypeIndex, groupKey)).rejects.toThrow(
                'Connection terminated unexpectedly'
            )

            expect(mockPostgres.query).toHaveBeenCalledWith(
                PostgresUse.PERSONS_WRITE,
                expect.stringContaining('SELECT * FROM posthog_group'),
                [teamId, groupTypeIndex, groupKey],
                'fetchGroup'
            )
        })

        it('should handle constraint violations', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            // Try to insert the same group again (should fail due to unique constraint)
            await expect(
                repository.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    groupProperties,
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation
                )
            ).rejects.toThrow('Parallel posthog_group inserts, retry')
        })
    })

    describe('edge cases', () => {
        it('should handle empty group properties', async () => {
            await insertTestTeam(teamId)

            const emptyProperties = {}

            const result = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                emptyProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.group_properties).toEqual(emptyProperties)
        })

        it('should handle null values in properties', async () => {
            await insertTestTeam(teamId)

            const nullProperties = {
                nullValue: null,
                undefinedValue: undefined,
                emptyString: '',
                zeroValue: 0,
                falseValue: false,
            }

            const result = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                nullProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            // Note: undefined values are stripped during JSON serialization
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.group_properties).toMatchObject({
                nullValue: null,
                emptyString: '',
                zeroValue: 0,
                falseValue: false,
            })
            expect(fetchedGroup?.group_properties).not.toHaveProperty('undefinedValue')
        })

        it('should handle very large properties', async () => {
            await insertTestTeam(teamId)

            const largeProperties = {
                largeString: 'x'.repeat(10000),
                largeArray: Array(1000).fill('test'),
                nestedObject: {
                    level1: {
                        level2: {
                            level3: {
                                value: 'deep nested value',
                            },
                        },
                    },
                },
            }

            const result = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                largeProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.group_properties).toMatchObject(largeProperties)
        })

        it('should handle special characters in group key', async () => {
            await insertTestTeam(teamId)

            const specialGroupKey = 'group-key-with-special-chars!@#$%^&*()_+-=[]{}|;:,.<>?'

            const result = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                specialGroupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, specialGroupKey)
            expect(fetchedGroup?.group_key).toBe(specialGroupKey)
        })

        it('should handle empty group key', async () => {
            await insertTestTeam(teamId)

            const emptyGroupKey = ''

            const result = await repository.insertGroup(
                teamId,
                groupTypeIndex,
                emptyGroupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, emptyGroupKey)
            expect(fetchedGroup?.group_key).toBe(emptyGroupKey)
        })

        it('should handle extreme group type indices', async () => {
            await insertTestTeam(teamId)

            const extremeGroupTypeIndex = 4 as GroupTypeIndex // Maximum valid value

            const result = await repository.insertGroup(
                teamId,
                extremeGroupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            const fetchedGroup = await repository.fetchGroup(teamId, extremeGroupTypeIndex, groupKey)
            expect(fetchedGroup?.group_type_index).toBe(extremeGroupTypeIndex)
        })

        it('should handle empty properties in update', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const emptyProperties = {}

            const result = await repository.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                emptyProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                'empty-update'
            )

            expect(result).toBe(2)

            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.group_properties).toEqual(emptyProperties)
        })

        it('should handle optimistic update with version 0', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup({ version: 0 })

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                0, // expectedVersion
                { name: 'Updated from version 0' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBe(1)

            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.version).toBe(1)
            expect(fetchedGroup?.group_properties).toMatchObject({ name: 'Updated from version 0' })
        })

        it('should handle optimistic update with wrong version', async () => {
            await insertTestTeam(teamId)
            await insertTestGroup()

            const result = await repository.updateGroupOptimistically(
                teamId,
                groupTypeIndex,
                groupKey,
                999, // wrong expectedVersion
                { name: 'This should not update' },
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            expect(result).toBeUndefined()

            // Verify the group was not updated
            const fetchedGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey)
            expect(fetchedGroup?.version).toBe(1)
            expect(fetchedGroup?.group_properties).toMatchObject(groupProperties)
        })
    })

    describe('insertGroupType', () => {
        it('should insert a new group type successfully', async () => {
            await insertTestTeam(teamId)

            const [groupTypeIndex, isInsert] = await repository.insertGroupType(
                teamId,
                teamId as ProjectId, // insertTestTeam creates project with id = teamId
                'company',
                0
            )

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(true)

            // Verify the group type was actually inserted
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, teamId, 'company'], // project_id = teamId because insertTestTeam creates project with id = teamId
                'test-fetch-group-type'
            )

            expect(rows).toHaveLength(1)
            expect(rows[0].team_id).toBe(teamId)
            expect(Number(rows[0].project_id)).toBe(teamId) // project_id should equal teamId
            expect(rows[0].group_type).toBe('company')
            expect(rows[0].group_type_index).toBe(0)
        })

        it('should return existing group type index when already exists', async () => {
            await insertTestTeam(teamId)

            // Insert the group type first
            await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)

            // Try to insert the same group type again
            const [groupTypeIndex, isInsert] = await repository.insertGroupType(
                teamId,
                teamId as ProjectId,
                'company',
                0
            )

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(false)

            // Verify only one record exists
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, teamId, 'company'],
                'test-fetch-group-type'
            )

            expect(rows).toHaveLength(1)
        })

        it('should handle index conflicts by incrementing', async () => {
            await insertTestTeam(teamId)

            // Insert first group type at index 0
            const [index1, isInsert1] = await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)
            expect(index1).toBe(0)
            expect(isInsert1).toBe(true)

            // Try to insert second group type at index 0 (should get index 1)
            const [index2, isInsert2] = await repository.insertGroupType(teamId, teamId as ProjectId, 'organization', 0)
            expect(index2).toBe(1)
            expect(isInsert2).toBe(true)

            // Try to insert third group type at index 0 (should get index 2)
            const [index3, isInsert3] = await repository.insertGroupType(teamId, teamId as ProjectId, 'team', 0)
            expect(index3).toBe(2)
            expect(isInsert3).toBe(true)
        })

        it('should respect the maximum group types limit', async () => {
            await insertTestTeam(teamId)

            // Insert 5 group types (the maximum)
            for (let i = 0; i < 5; i++) {
                const [index, isInsert] = await repository.insertGroupType(
                    teamId,
                    teamId as ProjectId,
                    `group_type_${i}`,
                    i
                )
                expect(index).toBe(i)
                expect(isInsert).toBe(true)
            }

            // Try to insert the 6th group type (should fail)
            const [index6, isInsert6] = await repository.insertGroupType(teamId, teamId as ProjectId, 'group_type_6', 5)
            expect(index6).toBe(null)
            expect(isInsert6).toBe(false)
        })

        it('should handle different projects independently', async () => {
            const localTeamId1 = 10 as TeamId // Use unique IDs for this test
            const localTeamId2 = 11 as TeamId
            await insertTestTeam(localTeamId1)
            await insertTestTeam(localTeamId2)

            // Insert group type in first project
            const [index1, isInsert1] = await repository.insertGroupType(
                localTeamId1,
                localTeamId1 as ProjectId,
                'company',
                0
            )
            expect(index1).toBe(0)
            expect(isInsert1).toBe(true)

            // Insert same group type name in second project (should succeed)
            const [index2, isInsert2] = await repository.insertGroupType(
                localTeamId2,
                localTeamId2 as ProjectId,
                'company',
                0
            )
            expect(index2).toBe(0)
            expect(isInsert2).toBe(true)

            // Verify both exist independently
            const { rows: rows1 } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE project_id = $1',
                [localTeamId1],
                'test-fetch-project1'
            )
            const { rows: rows2 } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE project_id = $1',
                [localTeamId2],
                'test-fetch-project2'
            )

            expect(rows1).toHaveLength(1)
            expect(rows2).toHaveLength(1)
            expect(Number(rows1[0].project_id)).toBe(localTeamId1)
            expect(Number(rows2[0].project_id)).toBe(localTeamId2)
        })

        it('should handle race conditions gracefully', async () => {
            await insertTestTeam(teamId)

            // Simulate race condition by directly inserting a group type
            await insertRow(postgres, 'posthog_grouptypemapping', {
                team_id: teamId,
                project_id: teamId,
                group_type: 'company',
                group_type_index: 0,
                created_at: new Date().toISOString(),
            })

            // Now try to insert the same group type through the repository
            const [groupTypeIndex, isInsert] = await repository.insertGroupType(
                teamId,
                teamId as ProjectId,
                'company',
                0
            )

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(false)
        })

        it('should work within a transaction', async () => {
            await insertTestTeam(teamId)

            const result = await repository.inTransaction('test insertGroupType transaction', async (tx) => {
                return await tx.insertGroupType(teamId, teamId as ProjectId, 'company', 0)
            })

            expect(result).toEqual([0, true])

            // Verify the group type was actually inserted
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, teamId, 'company'],
                'test-fetch-group-type'
            )

            expect(rows).toHaveLength(1)
        })

        it('should work with raw transaction', async () => {
            await insertTestTeam(teamId)

            const result = await repository.inRawTransaction('test insertGroupType raw transaction', async (tx) => {
                return await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0, tx)
            })

            expect(result).toEqual([0, true])

            // Verify the group type was actually inserted
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, teamId, 'company'],
                'test-fetch-group-type'
            )

            expect(rows).toHaveLength(1)
        })

        it('should rollback transaction on error', async () => {
            await insertTestTeam(teamId)

            // Try to execute a transaction that will fail
            await expect(
                repository.inTransaction('failing insertGroupType transaction', async (tx) => {
                    // Insert a group type
                    await tx.insertGroupType(teamId, teamId as ProjectId, 'company', 0)

                    // This should cause the transaction to rollback
                    throw new Error('Simulated transaction failure')
                })
            ).rejects.toThrow('Simulated transaction failure')

            // Verify the group type was not inserted (transaction rolled back)
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2',
                [teamId, teamId],
                'test-fetch-group-types'
            )

            expect(rows).toHaveLength(0)
        })

        it('should handle special characters in group type names', async () => {
            await insertTestTeam(teamId)

            const specialGroupType = 'group-type-with-special-chars!@#$%^&*()_+-=[]{}|;:,.<>?'

            const [groupTypeIndex, isInsert] = await repository.insertGroupType(
                teamId,
                teamId as ProjectId,
                specialGroupType,
                0
            )

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(true)

            // Verify the group type was actually inserted
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, teamId, specialGroupType],
                'test-fetch-group-type'
            )

            expect(rows).toHaveLength(1)
            expect(rows[0].group_type).toBe(specialGroupType)
        })

        it('should handle empty group type names', async () => {
            await insertTestTeam(teamId)

            const emptyGroupType = ''

            const [groupTypeIndex, isInsert] = await repository.insertGroupType(
                teamId,
                teamId as ProjectId,
                emptyGroupType,
                0
            )

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(true)

            // Verify the group type was actually inserted
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, teamId, emptyGroupType],
                'test-fetch-group-type'
            )

            expect(rows).toHaveLength(1)
            expect(rows[0].group_type).toBe(emptyGroupType)
        })

        it('should handle very long group type names', async () => {
            await insertTestTeam(teamId)

            const longGroupType = 'x'.repeat(400) // 400 limit

            const [groupTypeIndex, isInsert] = await repository.insertGroupType(
                teamId,
                teamId as ProjectId,
                longGroupType,
                0
            )

            expect(groupTypeIndex).toBe(0)
            expect(isInsert).toBe(true)

            // Verify the group type was actually inserted
            const { rows } = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_grouptypemapping WHERE team_id = $1 AND project_id = $2 AND group_type = $3',
                [teamId, teamId, longGroupType],
                'test-fetch-group-type'
            )

            expect(rows).toHaveLength(1)
            expect(rows[0].group_type).toBe(longGroupType)
        })
    })

    describe('fetchGroupTypesByProjectIds', () => {
        it('should return empty object for empty project IDs array', async () => {
            const result = await repository.fetchGroupTypesByProjectIds([])
            expect(result).toEqual({})
        })

        it('should return empty arrays for projects with no group types', async () => {
            await insertTestTeam(teamId)
            const localTeamId2 = 10 as TeamId
            await insertTestTeam(localTeamId2)

            const result = await repository.fetchGroupTypesByProjectIds([
                teamId as ProjectId,
                localTeamId2 as ProjectId,
            ])

            expect(result).toEqual({
                [teamId]: [],
                [localTeamId2]: [],
            })
        })

        it('should fetch group types for single project', async () => {
            await insertTestTeam(teamId)

            // Insert some group types
            await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)
            await repository.insertGroupType(teamId, teamId as ProjectId, 'organization', 1)

            const result = await repository.fetchGroupTypesByProjectIds([teamId as ProjectId])

            expect(result).toEqual({
                [teamId]: [
                    { group_type: 'company', group_type_index: 0 },
                    { group_type: 'organization', group_type_index: 1 },
                ],
            })
        })

        it('should fetch group types for multiple projects', async () => {
            const localTeamId1 = 10 as TeamId
            const localTeamId2 = 11 as TeamId
            await insertTestTeam(localTeamId1)
            await insertTestTeam(localTeamId2)

            // Insert group types for first project
            await repository.insertGroupType(localTeamId1, localTeamId1 as ProjectId, 'company', 0)
            await repository.insertGroupType(localTeamId1, localTeamId1 as ProjectId, 'team', 1)

            // Insert group types for second project
            await repository.insertGroupType(localTeamId2, localTeamId2 as ProjectId, 'organization', 0)

            const result = await repository.fetchGroupTypesByProjectIds([
                localTeamId1 as ProjectId,
                localTeamId2 as ProjectId,
            ])

            expect(result).toEqual({
                [localTeamId1]: [
                    { group_type: 'company', group_type_index: 0 },
                    { group_type: 'team', group_type_index: 1 },
                ],
                [localTeamId2]: [{ group_type: 'organization', group_type_index: 0 }],
            })
        })

        it('should handle mix of projects with and without group types', async () => {
            const localTeamId1 = 12 as TeamId
            const localTeamId2 = 13 as TeamId
            await insertTestTeam(localTeamId1)
            await insertTestTeam(localTeamId2)

            // Only insert group types for first project
            await repository.insertGroupType(localTeamId1, localTeamId1 as ProjectId, 'company', 0)

            const result = await repository.fetchGroupTypesByProjectIds([
                localTeamId1 as ProjectId,
                localTeamId2 as ProjectId,
            ])

            expect(result).toEqual({
                [localTeamId1]: [{ group_type: 'company', group_type_index: 0 }],
                [localTeamId2]: [],
            })
        })

        it('should return correct types for group_type_index', async () => {
            await insertTestTeam(teamId)
            await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)

            const result = await repository.fetchGroupTypesByProjectIds([teamId as ProjectId])

            // Verify the type is GroupTypeIndex (the test will fail at compile time if not)
            const groupTypeIndex: GroupTypeIndex = result[teamId][0].group_type_index
            expect(groupTypeIndex).toBe(0)
        })
    })

    describe('fetchGroupTypesByTeamIds', () => {
        it('should return empty object for empty team IDs array', async () => {
            const result = await repository.fetchGroupTypesByTeamIds([])
            expect(result).toEqual({})
        })

        it('should return empty arrays for teams with no group types', async () => {
            await insertTestTeam(teamId)
            const localTeamId2 = 20 as TeamId
            await insertTestTeam(localTeamId2)

            const result = await repository.fetchGroupTypesByTeamIds([teamId, localTeamId2])

            expect(result).toEqual({
                [teamId]: [],
                [localTeamId2]: [],
            })
        })

        it('should fetch group types for single team', async () => {
            await insertTestTeam(teamId)

            // Insert some group types
            await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)
            await repository.insertGroupType(teamId, teamId as ProjectId, 'organization', 1)

            const result = await repository.fetchGroupTypesByTeamIds([teamId])

            expect(result).toEqual({
                [teamId]: [
                    { group_type: 'company', group_type_index: 0 },
                    { group_type: 'organization', group_type_index: 1 },
                ],
            })
        })

        it('should fetch group types for multiple teams', async () => {
            const localTeamId1 = 21 as TeamId
            const localTeamId2 = 22 as TeamId
            await insertTestTeam(localTeamId1)
            await insertTestTeam(localTeamId2)

            // Insert group types for first team
            await repository.insertGroupType(localTeamId1, localTeamId1 as ProjectId, 'company', 0)
            await repository.insertGroupType(localTeamId1, localTeamId1 as ProjectId, 'team', 1)

            // Insert group types for second team
            await repository.insertGroupType(localTeamId2, localTeamId2 as ProjectId, 'organization', 0)

            const result = await repository.fetchGroupTypesByTeamIds([localTeamId1, localTeamId2])

            expect(result).toEqual({
                [localTeamId1]: [
                    { group_type: 'company', group_type_index: 0 },
                    { group_type: 'team', group_type_index: 1 },
                ],
                [localTeamId2]: [{ group_type: 'organization', group_type_index: 0 }],
            })
        })

        it('should handle mix of teams with and without group types', async () => {
            const localTeamId1 = 23 as TeamId
            const localTeamId2 = 24 as TeamId
            await insertTestTeam(localTeamId1)
            await insertTestTeam(localTeamId2)

            // Only insert group types for first team
            await repository.insertGroupType(localTeamId1, localTeamId1 as ProjectId, 'company', 0)

            const result = await repository.fetchGroupTypesByTeamIds([localTeamId1, localTeamId2])

            expect(result).toEqual({
                [localTeamId1]: [{ group_type: 'company', group_type_index: 0 }],
                [localTeamId2]: [],
            })
        })

        it('should return correct types for group_type_index', async () => {
            await insertTestTeam(teamId)
            await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)

            const result = await repository.fetchGroupTypesByTeamIds([teamId])

            // Verify the type is GroupTypeIndex (the test will fail at compile time if not)
            const groupTypeIndex: GroupTypeIndex = result[teamId][0].group_type_index
            expect(groupTypeIndex).toBe(0)
        })
    })

    describe('fetchGroupsByKeys', () => {
        beforeEach(async () => {
            await insertTestTeam(teamId)
            // Insert group types
            await repository.insertGroupType(teamId, teamId as ProjectId, 'company', 0)
            await repository.insertGroupType(teamId, teamId as ProjectId, 'organization', 1)
        })

        it('should return empty array for empty inputs', async () => {
            expect(await repository.fetchGroupsByKeys([], [], [])).toEqual([])
            expect(await repository.fetchGroupsByKeys([teamId], [], [])).toEqual([])
            expect(await repository.fetchGroupsByKeys([], [0 as GroupTypeIndex], [])).toEqual([])
            expect(await repository.fetchGroupsByKeys([], [], ['key1'])).toEqual([])
        })

        it('should fetch single group by keys', async () => {
            const groupProperties = { name: 'PostHog Inc', industry: 'Technology' }

            // Insert a group
            await repository.insertGroup(
                teamId,
                0 as GroupTypeIndex,
                'posthog',
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation
            )

            const result = await repository.fetchGroupsByKeys([teamId], [0 as GroupTypeIndex], ['posthog'])

            expect(result).toHaveLength(1)
            expect(result[0]).toEqual({
                team_id: teamId,
                group_type_index: 0,
                group_key: 'posthog',
                group_properties: groupProperties,
            })
        })

        it('should fetch multiple groups by keys', async () => {
            const company1Props = { name: 'PostHog Inc', industry: 'Technology' }
            const company2Props = { name: 'Acme Corp', industry: 'Manufacturing' }
            const org1Props = { name: 'Engineering Team', department: 'Product' }

            // Insert multiple groups
            await repository.insertGroup(teamId, 0 as GroupTypeIndex, 'posthog', company1Props, createdAt, {}, {})
            await repository.insertGroup(teamId, 0 as GroupTypeIndex, 'acme', company2Props, createdAt, {}, {})
            await repository.insertGroup(teamId, 1 as GroupTypeIndex, 'eng-team', org1Props, createdAt, {}, {})

            const result = await repository.fetchGroupsByKeys(
                [teamId, teamId, teamId],
                [0 as GroupTypeIndex, 0 as GroupTypeIndex, 1 as GroupTypeIndex],
                ['posthog', 'acme', 'eng-team']
            )

            expect(result).toHaveLength(3)
            expect(result).toEqual(
                expect.arrayContaining([
                    {
                        team_id: teamId,
                        group_type_index: 0,
                        group_key: 'posthog',
                        group_properties: company1Props,
                    },
                    {
                        team_id: teamId,
                        group_type_index: 0,
                        group_key: 'acme',
                        group_properties: company2Props,
                    },
                    {
                        team_id: teamId,
                        group_type_index: 1,
                        group_key: 'eng-team',
                        group_properties: org1Props,
                    },
                ])
            )
        })

        it('should handle non-existent groups', async () => {
            const result = await repository.fetchGroupsByKeys([teamId], [0 as GroupTypeIndex], ['non-existent'])

            expect(result).toEqual([])
        })

        it('should handle mixed existing and non-existent groups', async () => {
            const groupProperties = { name: 'PostHog Inc' }

            // Insert only one group
            await repository.insertGroup(teamId, 0 as GroupTypeIndex, 'posthog', groupProperties, createdAt, {}, {})

            const result = await repository.fetchGroupsByKeys(
                [teamId, teamId],
                [0 as GroupTypeIndex, 0 as GroupTypeIndex],
                ['posthog', 'non-existent']
            )

            expect(result).toHaveLength(1)
            expect(result[0]).toEqual({
                team_id: teamId,
                group_type_index: 0,
                group_key: 'posthog',
                group_properties: groupProperties,
            })
        })

        it('should handle multiple teams', async () => {
            const localTeamId2 = 25 as TeamId
            await insertTestTeam(localTeamId2)
            await repository.insertGroupType(localTeamId2, localTeamId2 as ProjectId, 'company', 0)

            const team1Props = { name: 'Team 1 Company' }
            const team2Props = { name: 'Team 2 Company' }

            // Insert groups for both teams
            await repository.insertGroup(teamId, 0 as GroupTypeIndex, 'company1', team1Props, createdAt, {}, {})
            await repository.insertGroup(localTeamId2, 0 as GroupTypeIndex, 'company2', team2Props, createdAt, {}, {})

            const result = await repository.fetchGroupsByKeys(
                [teamId, localTeamId2],
                [0 as GroupTypeIndex, 0 as GroupTypeIndex],
                ['company1', 'company2']
            )

            expect(result).toHaveLength(2)
            expect(result).toEqual(
                expect.arrayContaining([
                    {
                        team_id: teamId,
                        group_type_index: 0,
                        group_key: 'company1',
                        group_properties: team1Props,
                    },
                    {
                        team_id: localTeamId2,
                        group_type_index: 0,
                        group_key: 'company2',
                        group_properties: team2Props,
                    },
                ])
            )
        })

        it('should return correct types', async () => {
            const groupProperties = { name: 'PostHog Inc' }

            await repository.insertGroup(teamId, 0 as GroupTypeIndex, 'posthog', groupProperties, createdAt, {}, {})

            const result = await repository.fetchGroupsByKeys([teamId], [0 as GroupTypeIndex], ['posthog'])

            // Verify types are correctly cast (will fail at compile time if not)
            const teamIdResult: TeamId = result[0].team_id
            const groupTypeIndexResult: GroupTypeIndex = result[0].group_type_index
            expect(teamIdResult).toBe(teamId)
            expect(groupTypeIndexResult).toBe(0)
        })
    })
})
