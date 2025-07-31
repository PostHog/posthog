import { DateTime } from 'luxon'

import { insertRow, resetTestDatabase } from '../../../../../tests/helpers/sql'
import {
    GroupTypeIndex,
    Hub,
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
            ).rejects.toThrow("can't enable both forUpdate and useReadReplica in db::fetchGroup")
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
})
