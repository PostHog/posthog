import { DateTime } from 'luxon'

import {
    InternalPersonWithDistinctId,
    PersonRepository,
} from '~/worker/ingestion/persons/repositories/person-repository'

import { PersonHogClient } from '../../../ingestion/personhog/client'
import { PersonHogPersonRepository } from '../../../ingestion/personhog/personhog-person-repository'
import { InternalPerson, TeamId } from '../../../types'
import { PersonsManagerService } from './persons-manager.service'

jest.mock('../../../utils/logger')

const TEAM_1 = 1 as TeamId
const TEAM_2 = 2 as TeamId

type MockPersonHogClient = {
    groups: jest.Mocked<
        Pick<
            PersonHogClient['groups'],
            'fetchGroup' | 'fetchGroupsByKeys' | 'fetchGroupTypesByTeamIds' | 'fetchGroupTypesByProjectIds'
        >
    >
    persons: jest.Mocked<Pick<PersonHogClient['persons'], 'fetchPersonsByDistinctIds' | 'fetchPersonsByPersonIds'>>
}

function createMockPostgres(persons: Record<string, any>[]): jest.Mocked<PersonRepository> {
    const mock: jest.Mocked<PersonRepository> = {
        fetchPerson: jest.fn(),
        fetchPersonsByDistinctIds: jest.fn(),
        fetchPersonsByPersonIds: jest.fn(),
        createPerson: jest.fn(),
        updatePerson: jest.fn(),
        updatePersonAssertVersion: jest.fn(),
        updatePersonsBatch: jest.fn(),
        deletePerson: jest.fn(),
        addDistinctId: jest.fn(),
        addPersonlessDistinctId: jest.fn(),
        addPersonlessDistinctIdForMerge: jest.fn(),
        addPersonlessDistinctIdsBatch: jest.fn(),
        personPropertiesSize: jest.fn(),
        updateCohortsAndFeatureFlagsForMerge: jest.fn(),
        inTransaction: jest.fn(),
    }

    mock.fetchPersonsByDistinctIds.mockImplementation((teamPersons) => {
        const results = persons.filter((p) =>
            teamPersons.some(
                (tp: { teamId: number; distinctId: string }) =>
                    tp.teamId === p.team_id && tp.distinctId === p.distinct_id
            )
        )
        return Promise.resolve(results as InternalPersonWithDistinctId[])
    })

    mock.fetchPersonsByPersonIds.mockImplementation((teamPersons) => {
        const results = persons.filter((p) =>
            teamPersons.some(
                (tp: { teamId: number; personId: string }) => tp.teamId === p.team_id && tp.personId === p.uuid
            )
        )
        return Promise.resolve(results as InternalPerson[])
    })

    return mock
}

function createMockGrpcClient(persons: Record<string, any>[]): MockPersonHogClient {
    return {
        groups: {
            fetchGroup: jest.fn(),
            fetchGroupsByKeys: jest.fn(),
            fetchGroupTypesByTeamIds: jest.fn(),
            fetchGroupTypesByProjectIds: jest.fn(),
        },
        persons: {
            fetchPersonsByDistinctIds: jest
                .fn()
                .mockImplementation((teamPersons: { teamId: number; distinctId: string }[]) => {
                    const results = persons.filter((p) =>
                        teamPersons.some((tp) => tp.teamId === p.team_id && tp.distinctId === p.distinct_id)
                    )
                    return Promise.resolve(results as InternalPersonWithDistinctId[])
                }),
            fetchPersonsByPersonIds: jest
                .fn()
                .mockImplementation((teamPersons: { teamId: number; personId: string }[]) => {
                    const results = persons.filter((p) =>
                        teamPersons.some((tp) => tp.teamId === p.team_id && tp.personId === p.uuid)
                    )
                    return Promise.resolve(results as InternalPerson[])
                }),
        },
    }
}

const MOCK_PERSONS = [
    {
        id: '1',
        uuid: 'aaaaaaaa-0000-0000-0000-000000000001',
        team_id: TEAM_1,
        properties: { name: 'Alice', email: 'alice@example.com' },
        properties_last_updated_at: {},
        properties_last_operation: null,
        created_at: DateTime.fromISO('2024-01-01T00:00:00Z', { zone: 'utc' }),
        version: 1,
        is_identified: true,
        is_user_id: null,
        last_seen_at: null,
        distinct_id: 'alice-distinct',
    },
    {
        id: '2',
        uuid: 'aaaaaaaa-0000-0000-0000-000000000002',
        team_id: TEAM_1,
        properties: { name: 'Bob' },
        properties_last_updated_at: {},
        properties_last_operation: null,
        created_at: DateTime.fromISO('2024-01-01T00:00:00Z', { zone: 'utc' }),
        version: 1,
        is_identified: true,
        is_user_id: null,
        last_seen_at: null,
        distinct_id: 'bob-distinct',
    },
    {
        id: '3',
        uuid: 'aaaaaaaa-0000-0000-0000-000000000003',
        team_id: TEAM_2,
        properties: { name: 'Alice Team 2' },
        properties_last_updated_at: {},
        properties_last_operation: null,
        created_at: DateTime.fromISO('2024-01-01T00:00:00Z', { zone: 'utc' }),
        version: 1,
        is_identified: true,
        is_user_id: null,
        last_seen_at: null,
        distinct_id: 'alice-distinct',
    },
]

describe('PersonsManagerService + PersonHogPersonRepository integration', () => {
    jest.setTimeout(1000)

    const mockTeamManager = {
        getTeam: jest.fn().mockImplementation((teamId: number) =>
            Promise.resolve({
                id: teamId,
                uuid: `team-uuid-${teamId}`,
                organization_id: 'org-1',
                person_display_name_properties: [],
            })
        ),
        hasAvailableFeature: jest.fn().mockResolvedValue(true),
    } as any

    describe.each([
        ['postgres (rollout 0%)', 0],
        ['grpc (rollout 100%)', 100],
    ])('%s', (_label, rolloutPercentage) => {
        let mockPostgres: jest.Mocked<PersonRepository>
        let mockGrpc: MockPersonHogClient
        let manager: PersonsManagerService

        beforeEach(() => {
            jest.restoreAllMocks()
            mockPostgres = createMockPostgres(MOCK_PERSONS)
            mockGrpc = createMockGrpcClient(MOCK_PERSONS)

            const personhogRepo = new PersonHogPersonRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                rolloutPercentage,
                'test'
            )
            manager = new PersonsManagerService(mockTeamManager, personhogRepo, 'http://localhost:8000')
        })

        it('looks up person by distinct_id', async () => {
            const result = await manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id')

            expect(result).toEqual({
                id: MOCK_PERSONS[0].uuid,
                properties: { name: 'Alice', email: 'alice@example.com' },
                name: 'alice-distinct',
                url: `http://localhost:8000/project/${TEAM_1}/person/alice-distinct`,
            })

            if (rolloutPercentage === 100) {
                expect(mockGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
            } else {
                expect(mockPostgres.fetchPersonsByDistinctIds).toHaveBeenCalled()
            }
        })

        it('looks up person by person_id', async () => {
            const result = await manager.getCyclotronPerson(TEAM_1, MOCK_PERSONS[0].uuid, 'person_id')

            expect(result).toEqual({
                id: MOCK_PERSONS[0].uuid,
                properties: { name: 'Alice', email: 'alice@example.com' },
                name: MOCK_PERSONS[0].uuid,
                url: `http://localhost:8000/project/${TEAM_1}/person/${MOCK_PERSONS[0].uuid}`,
            })

            if (rolloutPercentage === 100) {
                expect(mockGrpc.persons.fetchPersonsByPersonIds).toHaveBeenCalled()
            } else {
                expect(mockPostgres.fetchPersonsByPersonIds).toHaveBeenCalled()
            }
        })

        it('returns null for nonexistent person', async () => {
            const result = await manager.getCyclotronPerson(TEAM_1, 'nonexistent', 'distinct_id')

            expect(result).toBeNull()
        })

        it('isolates persons by team', async () => {
            const team1Result = await manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id')
            manager.clear()
            const team2Result = await manager.getCyclotronPerson(TEAM_2, 'alice-distinct', 'distinct_id')

            expect(team1Result!.properties).toEqual({ name: 'Alice', email: 'alice@example.com' })
            expect(team2Result!.properties).toEqual({ name: 'Alice Team 2' })
        })
    })

    describe('grpc fallback to postgres on error', () => {
        let mockPostgres: jest.Mocked<PersonRepository>
        let mockGrpc: MockPersonHogClient
        let manager: PersonsManagerService

        beforeEach(() => {
            jest.restoreAllMocks()
            mockPostgres = createMockPostgres(MOCK_PERSONS)
            mockGrpc = createMockGrpcClient(MOCK_PERSONS)

            const personhogRepo = new PersonHogPersonRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                100,
                'test'
            )
            manager = new PersonsManagerService(mockTeamManager, personhogRepo, 'http://localhost:8000')
        })

        it('falls back to postgres when gRPC fetchPersonsByDistinctIds fails', async () => {
            mockGrpc.persons.fetchPersonsByDistinctIds.mockRejectedValue(new Error('connection refused'))

            const result = await manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id')

            expect(result).toEqual({
                id: MOCK_PERSONS[0].uuid,
                properties: { name: 'Alice', email: 'alice@example.com' },
                name: 'alice-distinct',
                url: `http://localhost:8000/project/${TEAM_1}/person/alice-distinct`,
            })

            expect(mockGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
            expect(mockPostgres.fetchPersonsByDistinctIds).toHaveBeenCalled()
        })

        it('falls back to postgres when gRPC fetchPersonsByPersonIds fails', async () => {
            mockGrpc.persons.fetchPersonsByPersonIds.mockRejectedValue(new Error('timeout'))

            const result = await manager.getCyclotronPerson(TEAM_1, MOCK_PERSONS[0].uuid, 'person_id')

            expect(result).toBeDefined()
            expect(result!.id).toBe(MOCK_PERSONS[0].uuid)

            expect(mockGrpc.persons.fetchPersonsByPersonIds).toHaveBeenCalled()
            expect(mockPostgres.fetchPersonsByPersonIds).toHaveBeenCalled()
        })

        it('produces identical output on fallback as on direct postgres path', async () => {
            // First: get the postgres-only result
            const postgresRepo = new PersonHogPersonRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                0,
                'test'
            )
            const postgresManager = new PersonsManagerService(mockTeamManager, postgresRepo, 'http://localhost:8000')

            const postgresResult = await postgresManager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id')

            // Second: get the fallback result (gRPC fails)
            mockGrpc.persons.fetchPersonsByDistinctIds.mockRejectedValue(new Error('down'))
            mockGrpc.persons.fetchPersonsByPersonIds.mockRejectedValue(new Error('down'))

            const fallbackResult = await manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id')

            expect(fallbackResult).toEqual(postgresResult)
        })
    })

    describe('concurrent multi-team lookup', () => {
        it('resolves persons from multiple teams concurrently', async () => {
            const mockPostgres = createMockPostgres(MOCK_PERSONS)
            const mockGrpc = createMockGrpcClient(MOCK_PERSONS)

            const personhogRepo = new PersonHogPersonRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                100,
                'test'
            )
            const manager = new PersonsManagerService(mockTeamManager, personhogRepo, 'http://localhost:8000')

            const [team1Result, team2Result] = await Promise.all([
                manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id'),
                manager.getCyclotronPerson(TEAM_2, 'alice-distinct', 'distinct_id'),
            ])

            expect(team1Result!.properties).toEqual({ name: 'Alice', email: 'alice@example.com' })
            expect(team2Result!.properties).toEqual({ name: 'Alice Team 2' })

            expect(mockGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
        })
    })
})
