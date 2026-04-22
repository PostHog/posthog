import { create } from '@bufbuild/protobuf'
import { Code, ConnectError, createRouterTransport } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import { PersonSchema } from '../../generated/personhog/personhog/types/v1/person_pb'
import { InternalPerson, TeamId } from '../../types'
import {
    InternalPersonWithDistinctId,
    PersonRepository,
} from '../../worker/ingestion/persons/repositories/person-repository'
import { PersonHogClient } from './client'
import { PersonHogPersonRepository } from './personhog-person-repository'

jest.mock('../../utils/logger')

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

const TEAM_ID = 1 as TeamId
const CREATED_AT = DateTime.fromISO('2024-01-01T00:00:00Z', { zone: 'utc' })

const TEST_PERSON: InternalPerson = {
    id: '42',
    uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    team_id: TEAM_ID,
    properties: { name: 'Test User', email: 'test@example.com' },
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: CREATED_AT,
    version: 1,
    is_identified: true,
    is_user_id: null,
    last_seen_at: null,
}

const TEST_PERSON_WITH_DISTINCT_ID: InternalPersonWithDistinctId = {
    ...TEST_PERSON,
    distinct_id: 'user-123',
}

function makeProtoPerson(
    overrides: Partial<{
        id: bigint
        uuid: string
        teamId: bigint
        properties: Uint8Array
        propertiesLastUpdatedAt: Uint8Array
        propertiesLastOperation: Uint8Array
        createdAt: bigint
        version: bigint
        isIdentified: boolean
        isUserId: boolean
        lastSeenAt: bigint
    }> = {}
) {
    return create(PersonSchema, {
        id: 42n,
        uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        teamId: BigInt(TEAM_ID),
        properties: jsonBytes({ name: 'Test User', email: 'test@example.com' }),
        propertiesLastUpdatedAt: jsonBytes({}),
        propertiesLastOperation: jsonBytes({}),
        createdAt: BigInt(CREATED_AT.toMillis()),
        version: 1n,
        isIdentified: true,
        ...overrides,
    })
}

function createMockPostgres(): jest.Mocked<PersonRepository> {
    return {
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
}

type ServiceHandlers = {
    getPersonsByDistinctIds: jest.Mock
    getPersonsByUuids: jest.Mock
}

function createGrpcClient(): { client: PersonHogClient; handlers: ServiceHandlers } {
    const handlers: ServiceHandlers = {
        getPersonsByDistinctIds: jest.fn(() => ({ results: [] })),
        getPersonsByUuids: jest.fn(() => ({ persons: [], missingIds: [] })),
    }

    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            ...handlers,
            // no-op defaults for RPCs not under test
            getPerson: () => ({}),
            getPersons: () => ({ persons: [], missingIds: [] }),
            getPersonByUuid: () => ({}),
            getPersonByDistinctId: () => ({}),
            getPersonsByDistinctIdsInTeam: () => ({ results: [] }),
            getDistinctIdsForPerson: () => ({ distinctIds: [] }),
            getDistinctIdsForPersons: () => ({ personDistinctIds: [] }),
            getGroup: () => ({}),
            getGroups: () => ({ groups: [], missingGroups: [] }),
            getGroupsBatch: () => ({ results: [] }),
            getGroupTypeMappingsByTeamId: () => ({ mappings: [] }),
            getGroupTypeMappingsByTeamIds: () => ({ results: [] }),
            getGroupTypeMappingsByProjectId: () => ({ mappings: [] }),
            getGroupTypeMappingsByProjectIds: () => ({ results: [] }),
            getHashKeyOverrideContext: () => ({ results: [] }),
            upsertHashKeyOverrides: () => ({}),
            deleteHashKeyOverridesByTeams: () => ({}),
            checkCohortMembership: () => ({ memberships: [] }),
            countCohortMembers: () => ({ count: 0n }),
            deleteCohortMember: () => ({ deleted: false }),
            deleteCohortMembersBulk: () => ({ deletedCount: 0n }),
            insertCohortMembers: () => ({ insertedCount: 0n }),
            listCohortMemberIds: () => ({ personIds: [], nextCursor: 0n }),
            updatePersonProperties: () => ({}),
        })
    })

    return { client: PersonHogClient.fromTransport(transport), handlers }
}

describe('PersonHogPersonRepository', () => {
    let mockPostgres: jest.Mocked<PersonRepository>
    let grpcClient: PersonHogClient
    let handlers: ServiceHandlers

    beforeEach(() => {
        mockPostgres = createMockPostgres()
        const grpc = createGrpcClient()
        grpcClient = grpc.client
        handlers = grpc.handlers
    })

    function createRepo(grpcPercentage: number, rolloutTeamIds: Set<number> = new Set()): PersonHogPersonRepository {
        return new PersonHogPersonRepository(mockPostgres, grpcClient, grpcPercentage, rolloutTeamIds, 'test')
    }

    describe.each([
        ['postgres (rollout 0%)', 0],
        ['grpc (rollout 100%)', 100],
    ])('read path: %s', (_label, rolloutPercentage) => {
        const expectGrpc = rolloutPercentage === 100

        describe('fetchPerson', () => {
            it('returns the person for a replica read', async () => {
                mockPostgres.fetchPerson.mockResolvedValue(TEST_PERSON)
                handlers.getPersonsByDistinctIds.mockReturnValue({
                    results: [
                        {
                            key: { teamId: BigInt(TEAM_ID), distinctId: 'user-123' },
                            person: makeProtoPerson(),
                        },
                    ],
                })

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchPerson(TEAM_ID, 'user-123', { useReadReplica: true })

                expect(result).toEqual(expectGrpc ? TEST_PERSON_WITH_DISTINCT_ID : TEST_PERSON)
                if (expectGrpc) {
                    expect(handlers.getPersonsByDistinctIds).toHaveBeenCalled()
                    expect(mockPostgres.fetchPerson).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchPerson).toHaveBeenCalledWith(TEAM_ID, 'user-123', {
                        useReadReplica: true,
                    })
                    expect(handlers.getPersonsByDistinctIds).not.toHaveBeenCalled()
                }
            })

            it('returns undefined when the person does not exist', async () => {
                mockPostgres.fetchPerson.mockResolvedValue(undefined)
                handlers.getPersonsByDistinctIds.mockReturnValue({ results: [] })

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchPerson(TEAM_ID, 'nonexistent', { useReadReplica: true })

                expect(result).toBeUndefined()
            })
        })

        describe('fetchPersonsByDistinctIds', () => {
            it('returns matching persons', async () => {
                mockPostgres.fetchPersonsByDistinctIds.mockResolvedValue([TEST_PERSON_WITH_DISTINCT_ID])
                handlers.getPersonsByDistinctIds.mockReturnValue({
                    results: [
                        {
                            key: { teamId: BigInt(TEAM_ID), distinctId: 'user-123' },
                            person: makeProtoPerson(),
                        },
                    ],
                })

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchPersonsByDistinctIds([{ teamId: TEAM_ID, distinctId: 'user-123' }], true)

                expect(result).toEqual([TEST_PERSON_WITH_DISTINCT_ID])
                if (expectGrpc) {
                    expect(handlers.getPersonsByDistinctIds).toHaveBeenCalled()
                    expect(mockPostgres.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchPersonsByDistinctIds).toHaveBeenCalledWith(
                        [{ teamId: TEAM_ID, distinctId: 'user-123' }],
                        true
                    )
                    expect(handlers.getPersonsByDistinctIds).not.toHaveBeenCalled()
                }
            })

            it('returns empty array for empty input', async () => {
                mockPostgres.fetchPersonsByDistinctIds.mockResolvedValue([])

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchPersonsByDistinctIds([], true)

                expect(result).toEqual([])
            })
        })

        describe('fetchPersonsByPersonIds', () => {
            it('returns matching persons', async () => {
                mockPostgres.fetchPersonsByPersonIds.mockResolvedValue([TEST_PERSON])
                handlers.getPersonsByUuids.mockReturnValue({
                    persons: [makeProtoPerson()],
                    missingIds: [],
                })

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchPersonsByPersonIds(
                    [{ teamId: TEAM_ID, personId: TEST_PERSON.uuid }],
                    true
                )

                expect(result).toEqual([TEST_PERSON])
                if (expectGrpc) {
                    expect(handlers.getPersonsByUuids).toHaveBeenCalled()
                    expect(mockPostgres.fetchPersonsByPersonIds).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchPersonsByPersonIds).toHaveBeenCalledWith(
                        [{ teamId: TEAM_ID, personId: TEST_PERSON.uuid }],
                        true
                    )
                    expect(handlers.getPersonsByUuids).not.toHaveBeenCalled()
                }
            })

            it('returns empty array for empty input', async () => {
                mockPostgres.fetchPersonsByPersonIds.mockResolvedValue([])

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchPersonsByPersonIds([], true)

                expect(result).toEqual([])
            })
        })
    })

    describe('team ID-based rollout', () => {
        it('routes to gRPC when team ID is in rollout set (percentage 0)', async () => {
            handlers.getPersonsByDistinctIds.mockReturnValue({
                results: [
                    {
                        key: { teamId: BigInt(TEAM_ID), distinctId: 'user-123' },
                        person: makeProtoPerson(),
                    },
                ],
            })

            const repo = createRepo(0, new Set([TEAM_ID]))
            const result = await repo.fetchPerson(TEAM_ID, 'user-123', { useReadReplica: true })

            expect(result).toEqual(TEST_PERSON_WITH_DISTINCT_ID)
            expect(handlers.getPersonsByDistinctIds).toHaveBeenCalled()
            expect(mockPostgres.fetchPerson).not.toHaveBeenCalled()
        })

        it('routes to postgres when team ID is not in rollout set (percentage 0)', async () => {
            mockPostgres.fetchPerson.mockResolvedValue(TEST_PERSON)

            const repo = createRepo(0, new Set([999 as TeamId]))
            const result = await repo.fetchPerson(TEAM_ID, 'user-123', { useReadReplica: true })

            expect(result).toEqual(TEST_PERSON)
            expect(mockPostgres.fetchPerson).toHaveBeenCalled()
            expect(handlers.getPersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('ignores percentage when team IDs are set', async () => {
            mockPostgres.fetchPerson.mockResolvedValue(TEST_PERSON)

            // percentage is 100 but team ID is not in the set — should use postgres
            const repo = createRepo(100, new Set([999 as TeamId]))
            const result = await repo.fetchPerson(TEAM_ID, 'user-123', { useReadReplica: true })

            expect(result).toEqual(TEST_PERSON)
            expect(mockPostgres.fetchPerson).toHaveBeenCalled()
            expect(handlers.getPersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('routes fetchPersonsByDistinctIds to gRPC when all team IDs are in rollout set', async () => {
            handlers.getPersonsByDistinctIds.mockReturnValue({
                results: [
                    {
                        key: { teamId: BigInt(TEAM_ID), distinctId: 'user-123' },
                        person: makeProtoPerson(),
                    },
                ],
            })

            const repo = createRepo(0, new Set([TEAM_ID]))
            const result = await repo.fetchPersonsByDistinctIds([{ teamId: TEAM_ID, distinctId: 'user-123' }], true)

            expect(result).toEqual([TEST_PERSON_WITH_DISTINCT_ID])
            expect(handlers.getPersonsByDistinctIds).toHaveBeenCalled()
            expect(mockPostgres.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
        })
    })

    describe('fetchPerson always uses postgres when', () => {
        it.each([
            ['forUpdate is true', { forUpdate: true, useReadReplica: true }],
            ['useReadReplica is false', { forUpdate: false, useReadReplica: false }],
            ['useReadReplica is not set', { forUpdate: false }],
            ['no options provided', undefined],
        ])('%s', async (_label, options) => {
            mockPostgres.fetchPerson.mockResolvedValue(TEST_PERSON)
            const repo = createRepo(100)

            const result = await repo.fetchPerson(TEAM_ID, 'user-123', options)

            expect(result).toEqual(TEST_PERSON)
            expect(mockPostgres.fetchPerson).toHaveBeenCalledWith(TEAM_ID, 'user-123', options)
            expect(handlers.getPersonsByDistinctIds).not.toHaveBeenCalled()
        })
    })

    describe('fetchPersonsByDistinctIds always uses postgres when useReadReplica is false', () => {
        it('useReadReplica is false', async () => {
            mockPostgres.fetchPersonsByDistinctIds.mockResolvedValue([TEST_PERSON_WITH_DISTINCT_ID])
            const repo = createRepo(100)

            const result = await repo.fetchPersonsByDistinctIds([{ teamId: TEAM_ID, distinctId: 'user-123' }], false)

            expect(result).toEqual([TEST_PERSON_WITH_DISTINCT_ID])
            expect(mockPostgres.fetchPersonsByDistinctIds).toHaveBeenCalled()
            expect(handlers.getPersonsByDistinctIds).not.toHaveBeenCalled()
        })
    })

    describe('grpc fallback to postgres on error', () => {
        it.each([
            [
                'fetchPerson',
                (h: ServiceHandlers, pg: jest.Mocked<PersonRepository>) => {
                    h.getPersonsByDistinctIds.mockImplementation(() => {
                        throw new ConnectError('connection refused', Code.Unavailable)
                    })
                    pg.fetchPerson.mockResolvedValue(TEST_PERSON)
                    return {
                        call: (repo: PersonHogPersonRepository) =>
                            repo.fetchPerson(TEAM_ID, 'user-123', { useReadReplica: true }),
                        expected: TEST_PERSON,
                    }
                },
            ],
            [
                'fetchPersonsByDistinctIds',
                (h: ServiceHandlers, pg: jest.Mocked<PersonRepository>) => {
                    h.getPersonsByDistinctIds.mockImplementation(() => {
                        throw new ConnectError('timeout', Code.DeadlineExceeded)
                    })
                    pg.fetchPersonsByDistinctIds.mockResolvedValue([TEST_PERSON_WITH_DISTINCT_ID])
                    return {
                        call: (repo: PersonHogPersonRepository) =>
                            repo.fetchPersonsByDistinctIds([{ teamId: TEAM_ID, distinctId: 'user-123' }], true),
                        expected: [TEST_PERSON_WITH_DISTINCT_ID],
                    }
                },
            ],
            [
                'fetchPersonsByPersonIds',
                (h: ServiceHandlers, pg: jest.Mocked<PersonRepository>) => {
                    h.getPersonsByUuids.mockImplementation(() => {
                        throw new ConnectError('unavailable', Code.Unavailable)
                    })
                    pg.fetchPersonsByPersonIds.mockResolvedValue([TEST_PERSON])
                    return {
                        call: (repo: PersonHogPersonRepository) =>
                            repo.fetchPersonsByPersonIds([{ teamId: TEAM_ID, personId: TEST_PERSON.uuid }], true),
                        expected: [TEST_PERSON],
                    }
                },
            ],
        ])(
            '%s falls back to postgres',
            async (
                _method,
                setup: (
                    h: ServiceHandlers,
                    pg: jest.Mocked<PersonRepository>
                ) => { call: (repo: PersonHogPersonRepository) => Promise<unknown>; expected: unknown }
            ) => {
                const { call, expected } = setup(handlers, mockPostgres)
                const repo = createRepo(100)

                const result = await call(repo)

                expect(result).toEqual(expected)
            }
        )
    })

    describe('write operations always delegate to postgres', () => {
        it('createPerson', async () => {
            const mockResult = { success: true as const, person: TEST_PERSON, messages: [], created: true as const }
            mockPostgres.createPerson.mockResolvedValue(mockResult)
            const repo = createRepo(100)
            const now = DateTime.utc()

            const result = await repo.createPerson(now, { name: 'test' }, {}, {}, TEAM_ID, null, false, 'uuid-123', {
                distinctId: 'dist-1',
            })

            expect(result).toBe(mockResult)
            expect(mockPostgres.createPerson).toHaveBeenCalled()
        })

        it('updatePerson', async () => {
            const mockResult: [InternalPerson, any[], boolean] = [TEST_PERSON, [], false]
            mockPostgres.updatePerson.mockResolvedValue(mockResult)
            const repo = createRepo(100)

            const result = await repo.updatePerson(TEST_PERSON, {
                properties: {},
                properties_last_updated_at: {},
                properties_last_operation: null,
                is_identified: true,
                created_at: CREATED_AT,
            })

            expect(result).toBe(mockResult)
            expect(mockPostgres.updatePerson).toHaveBeenCalled()
        })

        it('deletePerson', async () => {
            mockPostgres.deletePerson.mockResolvedValue([])
            const repo = createRepo(100)

            await repo.deletePerson(TEST_PERSON)

            expect(mockPostgres.deletePerson).toHaveBeenCalledWith(TEST_PERSON)
        })

        it('addDistinctId', async () => {
            mockPostgres.addDistinctId.mockResolvedValue([])
            const repo = createRepo(100)

            await repo.addDistinctId(TEST_PERSON, 'new-distinct-id', 1)

            expect(mockPostgres.addDistinctId).toHaveBeenCalledWith(TEST_PERSON, 'new-distinct-id', 1)
        })

        it('inTransaction', async () => {
            mockPostgres.inTransaction.mockImplementation((_desc, fn) => fn({} as any))
            const repo = createRepo(100)

            await repo.inTransaction('test', () => Promise.resolve('done'))

            expect(mockPostgres.inTransaction).toHaveBeenCalled()
        })
    })
})
