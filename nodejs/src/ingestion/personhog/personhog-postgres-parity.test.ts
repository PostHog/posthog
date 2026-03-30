import { create } from '@bufbuild/protobuf'
import { createRouterTransport } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { insertRow, resetTestDatabase } from '../../../tests/helpers/sql'
import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import {
    GroupSchema,
    GroupTypeMappingSchema,
    GroupTypeMappingsByKeySchema,
} from '../../generated/personhog/personhog/types/v1/group_pb'
import type { Group as ProtoGroup } from '../../generated/personhog/personhog/types/v1/group_pb'
import { GroupTypeIndex, Hub, ProjectId, PropertyUpdateOperation, TeamId } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { PostgresUse } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { PostgresGroupRepository } from '../../worker/ingestion/groups/repositories/postgres-group-repository'
import { PersonHogClient } from './client'

jest.mock('../../utils/logger')

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

/**
 * Build a proto Group that mirrors a postgres row, as a real personhog-router
 * service would return it. The conversion rules are:
 *   - ids/version → bigint
 *   - created_at → epoch milliseconds as bigint
 *   - JSON columns → UTF-8 encoded bytes
 */
function postgresRowToProtoGroup(row: {
    id?: number
    team_id: number
    group_type_index: number
    group_key: string
    group_properties: Record<string, any>
    properties_last_updated_at?: Record<string, any>
    properties_last_operation?: Record<string, any>
    created_at: DateTime
    version: number
}): ProtoGroup {
    return create(GroupSchema, {
        id: BigInt(row.id ?? 0),
        teamId: BigInt(row.team_id),
        groupTypeIndex: row.group_type_index,
        groupKey: row.group_key,
        groupProperties: jsonBytes(row.group_properties),
        propertiesLastUpdatedAt: jsonBytes(row.properties_last_updated_at ?? {}),
        propertiesLastOperation: jsonBytes(row.properties_last_operation ?? {}),
        createdAt: BigInt(row.created_at.toMillis()),
        version: BigInt(row.version),
    })
}

describe('PersonHog ↔ Postgres parity', () => {
    let hub: Hub
    let postgresRepo: PostgresGroupRepository

    const teamId = 1 as TeamId
    const projectId = teamId as unknown as ProjectId
    const createdAt = DateTime.fromISO('2023-06-15T12:30:45.123Z').toUTC()

    const insertTestTeam = async (id: number) => {
        await insertRow(hub.postgres, 'posthog_project', {
            id,
            organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
            name: `Test Project ${id}`,
            created_at: new Date().toISOString(),
        })
        await insertRow(hub.postgres, 'posthog_team', {
            id,
            name: `Test Team ${id}`,
            organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
            project_id: id,
            uuid: new UUIDT().toString(),
            api_token: `test-api-token-${id}`,
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

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        postgresRepo = new PostgresGroupRepository(hub.postgres)
        await insertTestTeam(teamId)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    /**
     * Helper: read back the raw row from postgres so we can build an equivalent
     * proto response. This simulates what the personhog-router would do — read
     * from the same underlying data and serialize it as protobuf.
     */
    async function readRawGroup(tId: number, typeIndex: number, key: string) {
        const { rows } = await hub.postgres.query(
            PostgresUse.PERSONS_READ,
            `SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3`,
            [tId, typeIndex, key],
            'readRawGroup'
        )
        if (rows.length === 0) {
            return undefined
        }
        const row = rows[0]
        return {
            id: row.id,
            team_id: row.team_id,
            group_type_index: row.group_type_index,
            group_key: row.group_key,
            group_properties: row.group_properties,
            properties_last_updated_at: row.properties_last_updated_at,
            properties_last_operation: row.properties_last_operation,
            created_at: DateTime.fromISO(row.created_at).toUTC(),
            version: Number(row.version || 0),
        }
    }

    function createPersonHogClient(serviceImpl: Record<string, any>): PersonHogClient {
        const transport = createRouterTransport(({ service }) => {
            service(PersonHogService, {
                // no-op defaults for all RPCs
                getGroup: () => ({}),
                getGroups: () => ({ groups: [], missingGroups: [] }),
                getGroupsBatch: () => ({ results: [] }),
                getGroupTypeMappingsByTeamId: () => ({ mappings: [] }),
                getGroupTypeMappingsByTeamIds: () => ({ results: [] }),
                getGroupTypeMappingsByProjectId: () => ({ mappings: [] }),
                getGroupTypeMappingsByProjectIds: () => ({ results: [] }),
                getPerson: () => ({}),
                getPersons: () => ({ persons: [] }),
                getPersonByUuid: () => ({}),
                getPersonsByUuids: () => ({ persons: [] }),
                getPersonByDistinctId: () => ({}),
                getPersonsByDistinctIdsInTeam: () => ({ results: [] }),
                getPersonsByDistinctIds: () => ({ results: [] }),
                getDistinctIdsForPerson: () => ({ distinctIds: [] }),
                getDistinctIdsForPersons: () => ({ personDistinctIds: [] }),
                getHashKeyOverrideContext: () => ({ results: [] }),
                upsertHashKeyOverrides: () => ({}),
                deleteHashKeyOverridesByTeams: () => ({}),
                checkCohortMembership: () => ({ memberships: [] }),
                updatePersonProperties: () => ({}),
                // override with test-specific implementations
                ...serviceImpl,
            })
        })
        return PersonHogClient.fromTransport(transport)
    }

    describe('fetchGroup', () => {
        it('single group produces identical output', async () => {
            const props = { name: 'Acme Corp', industry: 'tech', employee_count: 150 }
            const lastUpdated = { name: '2023-06-15T12:30:45.123Z', industry: '2023-06-15T12:30:45.123Z' }
            const lastOp = { name: PropertyUpdateOperation.Set, industry: PropertyUpdateOperation.Set }

            await postgresRepo.insertGroup(teamId, 0 as GroupTypeIndex, 'acme', props, createdAt, lastUpdated, lastOp)

            const fromPostgres = await postgresRepo.fetchGroup(teamId, 0 as GroupTypeIndex, 'acme')
            const rawRow = await readRawGroup(teamId, 0, 'acme')

            const grpcClient = createPersonHogClient({
                getGroup: () => ({ group: postgresRowToProtoGroup(rawRow!) }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroup(teamId, 0, 'acme')

            expect(fromGrpc).toEqual(fromPostgres)
        })

        it('group not found produces identical output', async () => {
            const fromPostgres = await postgresRepo.fetchGroup(teamId, 0 as GroupTypeIndex, 'nonexistent')

            const grpcClient = createPersonHogClient({
                getGroup: () => ({}),
            })
            const fromGrpc = await grpcClient.groups.fetchGroup(teamId, 0, 'nonexistent')

            expect(fromGrpc).toEqual(fromPostgres)
            expect(fromGrpc).toBeUndefined()
        })

        it('group with complex nested properties produces identical output', async () => {
            const props = {
                org: { settings: { billing: { plan: 'enterprise' }, limits: { users: 500 } } },
                tags: ['b2b', 'saas'],
                active: true,
                score: 99.5,
                nullable: null,
            }

            await postgresRepo.insertGroup(teamId, 1 as GroupTypeIndex, 'complex', props, createdAt, {}, {})

            const fromPostgres = await postgresRepo.fetchGroup(teamId, 1 as GroupTypeIndex, 'complex')
            const rawRow = await readRawGroup(teamId, 1, 'complex')

            const grpcClient = createPersonHogClient({
                getGroup: () => ({ group: postgresRowToProtoGroup(rawRow!) }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroup(teamId, 1, 'complex')

            expect(fromGrpc).toEqual(fromPostgres)
        })

        it('group with unicode properties produces identical output', async () => {
            const props = { name: '日本語テスト', emoji: '🚀✨', quotes: 'he said "hello"' }

            await postgresRepo.insertGroup(teamId, 0 as GroupTypeIndex, 'grp-日本語', props, createdAt, {}, {})

            const fromPostgres = await postgresRepo.fetchGroup(teamId, 0 as GroupTypeIndex, 'grp-日本語')
            const rawRow = await readRawGroup(teamId, 0, 'grp-日本語')

            const grpcClient = createPersonHogClient({
                getGroup: () => ({ group: postgresRowToProtoGroup(rawRow!) }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroup(teamId, 0, 'grp-日本語')

            expect(fromGrpc).toEqual(fromPostgres)
        })
    })

    describe('fetchGroupsByKeys', () => {
        it('batch fetch produces identical output', async () => {
            await postgresRepo.insertGroup(teamId, 0 as GroupTypeIndex, 'acme', { name: 'Acme' }, createdAt, {}, {})
            await postgresRepo.insertGroup(
                teamId,
                1 as GroupTypeIndex,
                'eng-team',
                { name: 'Engineering' },
                createdAt,
                {},
                {}
            )

            const fromPostgres = await postgresRepo.fetchGroupsByKeys(
                [teamId, teamId],
                [0 as GroupTypeIndex, 1 as GroupTypeIndex],
                ['acme', 'eng-team']
            )

            // Build proto response from what postgres actually stored
            const rawAcme = await readRawGroup(teamId, 0, 'acme')
            const rawEng = await readRawGroup(teamId, 1, 'eng-team')

            const grpcClient = createPersonHogClient({
                getGroupsBatch: () => ({
                    results: [
                        {
                            key: { teamId: BigInt(teamId), groupTypeIndex: 0, groupKey: 'acme' },
                            group: postgresRowToProtoGroup(rawAcme!),
                        },
                        {
                            key: { teamId: BigInt(teamId), groupTypeIndex: 1, groupKey: 'eng-team' },
                            group: postgresRowToProtoGroup(rawEng!),
                        },
                    ],
                }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroupsByKeys([teamId, teamId], [0, 1], ['acme', 'eng-team'])

            expect(fromGrpc).toEqual(fromPostgres)
        })

        it('missing groups in batch produce identical output', async () => {
            await postgresRepo.insertGroup(teamId, 0 as GroupTypeIndex, 'exists', { name: 'Found' }, createdAt, {}, {})

            const fromPostgres = await postgresRepo.fetchGroupsByKeys(
                [teamId, teamId],
                [0 as GroupTypeIndex, 0 as GroupTypeIndex],
                ['exists', 'missing']
            )

            const rawExists = await readRawGroup(teamId, 0, 'exists')

            const grpcClient = createPersonHogClient({
                getGroupsBatch: () => ({
                    results: [
                        {
                            key: { teamId: BigInt(teamId), groupTypeIndex: 0, groupKey: 'exists' },
                            group: postgresRowToProtoGroup(rawExists!),
                        },
                        {
                            key: { teamId: BigInt(teamId), groupTypeIndex: 0, groupKey: 'missing' },
                            // no group — not found
                        },
                    ],
                }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroupsByKeys([teamId, teamId], [0, 0], ['exists', 'missing'])

            expect(fromGrpc).toEqual(fromPostgres)
        })

        it('empty input produces identical output', async () => {
            const fromPostgres = await postgresRepo.fetchGroupsByKeys([], [], [])

            const grpcClient = createPersonHogClient({})
            const fromGrpc = await grpcClient.groups.fetchGroupsByKeys([], [], [])

            expect(fromGrpc).toEqual(fromPostgres)
            expect(fromGrpc).toEqual([])
        })
    })

    describe('fetchGroupTypesByTeamIds', () => {
        it('team with multiple group types produces identical output', async () => {
            await postgresRepo.insertGroupType(teamId, projectId, 'company', 0)
            await postgresRepo.insertGroupType(teamId, projectId, 'organization', 1)

            const fromPostgres = await postgresRepo.fetchGroupTypesByTeamIds([teamId])

            const grpcClient = createPersonHogClient({
                getGroupTypeMappingsByTeamIds: () => ({
                    results: [
                        create(GroupTypeMappingsByKeySchema, {
                            key: BigInt(teamId),
                            mappings: [
                                create(GroupTypeMappingSchema, { groupType: 'company', groupTypeIndex: 0 }),
                                create(GroupTypeMappingSchema, { groupType: 'organization', groupTypeIndex: 1 }),
                            ],
                        }),
                    ],
                }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroupTypesByTeamIds([teamId])

            expect(fromGrpc).toEqual(fromPostgres)
        })

        it('team with no group types — known shape divergence', async () => {
            // Postgres pre-initializes empty arrays for all requested IDs.
            // PersonHogClient omits keys with no mappings.
            // Downstream code handles this with result[teamId] ?? [].
            const fromPostgres = await postgresRepo.fetchGroupTypesByTeamIds([teamId])

            const grpcClient = createPersonHogClient({
                getGroupTypeMappingsByTeamIds: () => ({ results: [] }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroupTypesByTeamIds([teamId])

            // Postgres: { "1": [] }, gRPC: {}
            expect(fromPostgres).toEqual({ [teamId]: [] })
            expect(fromGrpc).toEqual({})

            // But downstream access via ?? [] produces the same result
            expect(fromPostgres[teamId] ?? []).toEqual(fromGrpc[teamId] ?? [])
        })

        it('multiple teams with mixed data produces identical output for present keys', async () => {
            const teamId2 = 10 as TeamId
            await insertTestTeam(teamId2)

            await postgresRepo.insertGroupType(teamId, projectId, 'company', 0)
            // teamId2 has no group types

            const fromPostgres = await postgresRepo.fetchGroupTypesByTeamIds([teamId, teamId2])

            const grpcClient = createPersonHogClient({
                getGroupTypeMappingsByTeamIds: () => ({
                    results: [
                        create(GroupTypeMappingsByKeySchema, {
                            key: BigInt(teamId),
                            mappings: [create(GroupTypeMappingSchema, { groupType: 'company', groupTypeIndex: 0 })],
                        }),
                        // teamId2 omitted — no mappings
                    ],
                }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroupTypesByTeamIds([teamId, teamId2])

            // Teams with data match exactly
            expect(fromGrpc[teamId]).toEqual(fromPostgres[teamId])

            // Teams without data: shape divergence handled by ?? []
            expect(fromPostgres[teamId2]).toEqual([])
            expect(fromGrpc[teamId2]).toBeUndefined()
            expect(fromPostgres[teamId2] ?? []).toEqual(fromGrpc[teamId2] ?? [])
        })

        it('empty input produces identical output', async () => {
            const fromPostgres = await postgresRepo.fetchGroupTypesByTeamIds([])

            const grpcClient = createPersonHogClient({})
            const fromGrpc = await grpcClient.groups.fetchGroupTypesByTeamIds([])

            expect(fromGrpc).toEqual(fromPostgres)
            expect(fromGrpc).toEqual({})
        })
    })

    describe('fetchGroupTypesByProjectIds', () => {
        it('project with group types produces identical output', async () => {
            await postgresRepo.insertGroupType(teamId, projectId, 'workspace', 0)

            const fromPostgres = await postgresRepo.fetchGroupTypesByProjectIds([projectId])

            const grpcClient = createPersonHogClient({
                getGroupTypeMappingsByProjectIds: () => ({
                    results: [
                        create(GroupTypeMappingsByKeySchema, {
                            key: BigInt(projectId as number),
                            mappings: [create(GroupTypeMappingSchema, { groupType: 'workspace', groupTypeIndex: 0 })],
                        }),
                    ],
                }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroupTypesByProjectIds([projectId])

            expect(fromGrpc).toEqual(fromPostgres)
        })

        it('project with no group types — known shape divergence', async () => {
            const fromPostgres = await postgresRepo.fetchGroupTypesByProjectIds([projectId])

            const grpcClient = createPersonHogClient({
                getGroupTypeMappingsByProjectIds: () => ({ results: [] }),
            })
            const fromGrpc = await grpcClient.groups.fetchGroupTypesByProjectIds([projectId])

            expect(fromPostgres).toEqual({ [projectId]: [] })
            expect(fromGrpc).toEqual({})
            expect(fromPostgres[projectId] ?? []).toEqual(fromGrpc[projectId] ?? [])
        })

        it('empty input produces identical output', async () => {
            const fromPostgres = await postgresRepo.fetchGroupTypesByProjectIds([])

            const grpcClient = createPersonHogClient({})
            const fromGrpc = await grpcClient.groups.fetchGroupTypesByProjectIds([])

            expect(fromGrpc).toEqual(fromPostgres)
            expect(fromGrpc).toEqual({})
        })
    })
})
