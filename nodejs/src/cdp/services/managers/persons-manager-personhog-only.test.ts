import { DateTime } from 'luxon'

import { PersonHogClient } from '../../../ingestion/personhog/client'
import { PersonHogOnlyPersonRepository } from '../../../ingestion/personhog/personhog-only-person-repository'
import { InternalPerson, TeamId } from '../../../types'
import { InternalPersonWithDistinctId } from '../../../worker/ingestion/persons/repositories/person-repository'
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

describe('PersonsManagerService + PersonHogOnlyPersonRepository', () => {
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

    let mockGrpc: MockPersonHogClient
    let manager: PersonsManagerService

    beforeEach(() => {
        jest.restoreAllMocks()
        mockGrpc = createMockGrpcClient(MOCK_PERSONS)

        const repo = new PersonHogOnlyPersonRepository(mockGrpc as unknown as PersonHogClient, 'test')
        manager = new PersonsManagerService(mockTeamManager, repo, 'http://localhost:8000')
    })

    it('looks up person by distinct_id via gRPC', async () => {
        const result = await manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id')

        expect(result).toEqual({
            id: MOCK_PERSONS[0].uuid,
            properties: { name: 'Alice', email: 'alice@example.com' },
            name: 'alice-distinct',
            url: `http://localhost:8000/project/${TEAM_1}/person/alice-distinct`,
        })

        expect(mockGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
    })

    it('looks up person by person_id via gRPC', async () => {
        const result = await manager.getCyclotronPerson(TEAM_1, MOCK_PERSONS[0].uuid, 'person_id')

        expect(result).toEqual({
            id: MOCK_PERSONS[0].uuid,
            properties: { name: 'Alice', email: 'alice@example.com' },
            name: MOCK_PERSONS[0].uuid,
            url: `http://localhost:8000/project/${TEAM_1}/person/${MOCK_PERSONS[0].uuid}`,
        })

        expect(mockGrpc.persons.fetchPersonsByPersonIds).toHaveBeenCalled()
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

    it('resolves persons from multiple teams concurrently', async () => {
        const [team1Result, team2Result] = await Promise.all([
            manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id'),
            manager.getCyclotronPerson(TEAM_2, 'alice-distinct', 'distinct_id'),
        ])

        expect(team1Result!.properties).toEqual({ name: 'Alice', email: 'alice@example.com' })
        expect(team2Result!.properties).toEqual({ name: 'Alice Team 2' })
        expect(mockGrpc.persons.fetchPersonsByDistinctIds).toHaveBeenCalled()
    })

    describe('gRPC errors propagate without fallback', () => {
        it('propagates gRPC error on fetchPersonsByDistinctIds', async () => {
            mockGrpc.persons.fetchPersonsByDistinctIds.mockRejectedValue(new Error('connection refused'))

            await expect(manager.getCyclotronPerson(TEAM_1, 'alice-distinct', 'distinct_id')).rejects.toThrow(
                'connection refused'
            )
        })

        it('propagates gRPC error on fetchPersonsByPersonIds', async () => {
            mockGrpc.persons.fetchPersonsByPersonIds.mockRejectedValue(new Error('timeout'))

            await expect(manager.getCyclotronPerson(TEAM_1, MOCK_PERSONS[0].uuid, 'person_id')).rejects.toThrow(
                'timeout'
            )
        })
    })

    describe('write operations throw', () => {
        it('throws on createPerson', () => {
            const repo = new PersonHogOnlyPersonRepository(mockGrpc as unknown as PersonHogClient, 'test')
            expect(() =>
                repo.createPerson(DateTime.now(), {}, {}, {}, 1, null, false, 'uuid', { distinctId: 'test' })
            ).toThrow('does not support write operations')
        })

        it('throws on deletePerson', () => {
            const repo = new PersonHogOnlyPersonRepository(mockGrpc as unknown as PersonHogClient, 'test')
            expect(() => repo.deletePerson({} as any)).toThrow('does not support write operations')
        })

        it('throws on inTransaction', () => {
            const repo = new PersonHogOnlyPersonRepository(mockGrpc as unknown as PersonHogClient, 'test')
            expect(() => repo.inTransaction('test', async () => {})).toThrow('does not support write operations')
        })
    })
})
