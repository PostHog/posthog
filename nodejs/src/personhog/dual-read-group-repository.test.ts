import { DateTime } from 'luxon'

import { Group, GroupTypeIndex, ProjectId, TeamId } from '../types'
import { GroupRepository } from '../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonHogClient } from './client'
import { DualReadGroupRepository } from './dual-read-group-repository'

jest.mock('../utils/logger')

const TEAM_ID = 1 as TeamId
const GROUP_TYPE_INDEX = 0 as GroupTypeIndex
const GROUP_KEY = 'test-group'
const PROJECT_ID = 100 as ProjectId

const TEST_GROUP: Group = {
    id: 42,
    team_id: TEAM_ID,
    group_type_index: GROUP_TYPE_INDEX,
    group_key: GROUP_KEY,
    group_properties: { name: 'Acme Corp', industry: 'tech' },
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: DateTime.fromISO('2024-01-01T00:00:00Z', { zone: 'utc' }),
    version: 1,
}

const GROUP_TYPE_MAPPINGS = {
    [TEAM_ID.toString()]: [
        { group_type: 'organization', group_type_index: 0 as GroupTypeIndex },
        { group_type: 'project', group_type_index: 1 as GroupTypeIndex },
    ],
}

function createMockPostgres(): jest.Mocked<GroupRepository> {
    return {
        fetchGroup: jest.fn(),
        fetchGroupsByKeys: jest.fn(),
        fetchGroupTypesByTeamIds: jest.fn(),
        fetchGroupTypesByProjectIds: jest.fn(),
        insertGroup: jest.fn(),
        updateGroup: jest.fn(),
        updateGroupOptimistically: jest.fn(),
        insertGroupType: jest.fn(),
        inTransaction: jest.fn(),
    }
}

function createMockGrpcClient(): jest.Mocked<
    Pick<
        PersonHogClient,
        'fetchGroup' | 'fetchGroupsByKeys' | 'fetchGroupTypesByTeamIds' | 'fetchGroupTypesByProjectIds'
    >
> {
    return {
        fetchGroup: jest.fn(),
        fetchGroupsByKeys: jest.fn(),
        fetchGroupTypesByTeamIds: jest.fn(),
        fetchGroupTypesByProjectIds: jest.fn(),
    }
}

describe('DualReadGroupRepository', () => {
    let mockPostgres: jest.Mocked<GroupRepository>
    let mockGrpc: ReturnType<typeof createMockGrpcClient>

    beforeEach(() => {
        mockPostgres = createMockPostgres()
        mockGrpc = createMockGrpcClient()
    })

    function createRepo(grpcPercentage: number): DualReadGroupRepository {
        return new DualReadGroupRepository(mockPostgres, mockGrpc as unknown as PersonHogClient, grpcPercentage, 'test')
    }

    describe.each([
        ['postgres (rollout 0%)', 0],
        ['grpc (rollout 100%)', 100],
    ])('read path: %s', (_label, rolloutPercentage) => {
        const expectGrpc = rolloutPercentage === 100

        describe('fetchGroup', () => {
            it('returns the group for a replica read', async () => {
                mockPostgres.fetchGroup.mockResolvedValue(TEST_GROUP)
                mockGrpc.fetchGroup.mockResolvedValue(TEST_GROUP)

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { useReadReplica: true })

                expect(result).toEqual(TEST_GROUP)
                if (expectGrpc) {
                    expect(mockGrpc.fetchGroup).toHaveBeenCalledWith(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY)
                    expect(mockPostgres.fetchGroup).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroup).toHaveBeenCalledWith(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, {
                        useReadReplica: true,
                    })
                    expect(mockGrpc.fetchGroup).not.toHaveBeenCalled()
                }
            })

            it('returns undefined when the group does not exist', async () => {
                mockPostgres.fetchGroup.mockResolvedValue(undefined)
                mockGrpc.fetchGroup.mockResolvedValue(undefined)

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, 'nonexistent', { useReadReplica: true })

                expect(result).toBeUndefined()
            })
        })

        describe('fetchGroupsByKeys', () => {
            const expectedResult = [
                {
                    team_id: TEAM_ID,
                    group_type_index: GROUP_TYPE_INDEX,
                    group_key: GROUP_KEY,
                    group_properties: { name: 'Acme Corp' },
                },
            ]

            it('returns matching groups', async () => {
                mockPostgres.fetchGroupsByKeys.mockResolvedValue(expectedResult)
                mockGrpc.fetchGroupsByKeys.mockResolvedValue(expectedResult)

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupsByKeys([TEAM_ID], [GROUP_TYPE_INDEX], [GROUP_KEY])

                expect(result).toEqual(expectedResult)
                if (expectGrpc) {
                    expect(mockGrpc.fetchGroupsByKeys).toHaveBeenCalledWith([TEAM_ID], [GROUP_TYPE_INDEX], [GROUP_KEY])
                    expect(mockPostgres.fetchGroupsByKeys).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroupsByKeys).toHaveBeenCalledWith(
                        [TEAM_ID],
                        [GROUP_TYPE_INDEX],
                        [GROUP_KEY]
                    )
                    expect(mockGrpc.fetchGroupsByKeys).not.toHaveBeenCalled()
                }
            })

            it('returns empty array for empty input', async () => {
                mockPostgres.fetchGroupsByKeys.mockResolvedValue([])
                mockGrpc.fetchGroupsByKeys.mockResolvedValue([])

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupsByKeys([], [], [])

                expect(result).toEqual([])
            })
        })

        describe('fetchGroupTypesByTeamIds', () => {
            it('returns group type mappings', async () => {
                mockPostgres.fetchGroupTypesByTeamIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                mockGrpc.fetchGroupTypesByTeamIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupTypesByTeamIds([TEAM_ID])

                expect(result).toEqual(GROUP_TYPE_MAPPINGS)
                if (expectGrpc) {
                    expect(mockGrpc.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_ID])
                    expect(mockPostgres.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_ID])
                    expect(mockGrpc.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
                }
            })
        })

        describe('fetchGroupTypesByProjectIds', () => {
            it('returns group type mappings', async () => {
                mockPostgres.fetchGroupTypesByProjectIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                mockGrpc.fetchGroupTypesByProjectIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupTypesByProjectIds([PROJECT_ID])

                expect(result).toEqual(GROUP_TYPE_MAPPINGS)
                if (expectGrpc) {
                    expect(mockGrpc.fetchGroupTypesByProjectIds).toHaveBeenCalledWith([PROJECT_ID])
                    expect(mockPostgres.fetchGroupTypesByProjectIds).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroupTypesByProjectIds).toHaveBeenCalledWith([PROJECT_ID])
                    expect(mockGrpc.fetchGroupTypesByProjectIds).not.toHaveBeenCalled()
                }
            })
        })
    })

    describe('fetchGroup always uses postgres when', () => {
        it.each([
            ['forUpdate is true', { forUpdate: true, useReadReplica: true }],
            ['useReadReplica is false', { forUpdate: false, useReadReplica: false }],
            ['useReadReplica is not set', { forUpdate: false }],
            ['no options provided', undefined],
        ])('%s', async (_label, options) => {
            mockPostgres.fetchGroup.mockResolvedValue(TEST_GROUP)
            const repo = createRepo(100)

            const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, options)

            expect(result).toEqual(TEST_GROUP)
            expect(mockPostgres.fetchGroup).toHaveBeenCalledWith(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, options)
            expect(mockGrpc.fetchGroup).not.toHaveBeenCalled()
        })
    })

    describe('grpc fallback to postgres on error', () => {
        it.each([
            [
                'fetchGroup',
                () => {
                    mockGrpc.fetchGroup.mockRejectedValue(new Error('connection refused'))
                    mockPostgres.fetchGroup.mockResolvedValue(TEST_GROUP)
                    return {
                        call: (repo: DualReadGroupRepository) =>
                            repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { useReadReplica: true }),
                        expected: TEST_GROUP,
                    }
                },
            ],
            [
                'fetchGroupsByKeys',
                () => {
                    const expected = [
                        {
                            team_id: TEAM_ID,
                            group_type_index: GROUP_TYPE_INDEX,
                            group_key: GROUP_KEY,
                            group_properties: {},
                        },
                    ]
                    mockGrpc.fetchGroupsByKeys.mockRejectedValue(new Error('timeout'))
                    mockPostgres.fetchGroupsByKeys.mockResolvedValue(expected)
                    return {
                        call: (repo: DualReadGroupRepository) =>
                            repo.fetchGroupsByKeys([TEAM_ID], [GROUP_TYPE_INDEX], [GROUP_KEY]),
                        expected,
                    }
                },
            ],
            [
                'fetchGroupTypesByTeamIds',
                () => {
                    mockGrpc.fetchGroupTypesByTeamIds.mockRejectedValue(new Error('unavailable'))
                    mockPostgres.fetchGroupTypesByTeamIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                    return {
                        call: (repo: DualReadGroupRepository) => repo.fetchGroupTypesByTeamIds([TEAM_ID]),
                        expected: GROUP_TYPE_MAPPINGS,
                    }
                },
            ],
            [
                'fetchGroupTypesByProjectIds',
                () => {
                    mockGrpc.fetchGroupTypesByProjectIds.mockRejectedValue(new Error('unavailable'))
                    mockPostgres.fetchGroupTypesByProjectIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                    return {
                        call: (repo: DualReadGroupRepository) => repo.fetchGroupTypesByProjectIds([PROJECT_ID]),
                        expected: GROUP_TYPE_MAPPINGS,
                    }
                },
            ],
        ])('%s falls back to postgres', async (_method, setup) => {
            const { call, expected } = setup()
            const repo = createRepo(100)

            const result = await call(repo)

            expect(result).toEqual(expected)
        })
    })

    describe('gRPC empty result shape divergence from Postgres', () => {
        it('fetchGroupTypesByTeamIds with missing key works via ?? [] fallback', async () => {
            // gRPC returns {} when a team has no group types (key absent),
            // whereas Postgres returns { "5": [] } (key present with empty array).
            // Downstream code uses result[teamId] ?? [] so both shapes work.
            mockGrpc.fetchGroupTypesByTeamIds.mockResolvedValue({})
            jest.spyOn(Math, 'random').mockReturnValue(0) // force gRPC path

            const repo = createRepo(100)
            const result = await repo.fetchGroupTypesByTeamIds([5 as TeamId])

            expect(result).toEqual({})
            // The caller would access result["5"] ?? [] and get []
            expect(result['5'] ?? []).toEqual([])

            jest.spyOn(Math, 'random').mockRestore()
        })

        it('fetchGroupTypesByProjectIds with missing key works via ?? [] fallback', async () => {
            mockGrpc.fetchGroupTypesByProjectIds.mockResolvedValue({})
            jest.spyOn(Math, 'random').mockReturnValue(0) // force gRPC path

            const repo = createRepo(100)
            const result = await repo.fetchGroupTypesByProjectIds([200 as ProjectId])

            expect(result).toEqual({})
            expect(result['200'] ?? []).toEqual([])

            jest.spyOn(Math, 'random').mockRestore()
        })
    })

    describe('sticky routing decision within an event loop iteration', () => {
        it('consecutive calls share the same routing decision', async () => {
            const expectedTypes = {
                [TEAM_ID.toString()]: [{ group_type: 'organization', group_type_index: 0 as GroupTypeIndex }],
            }
            const expectedGroups = [
                {
                    team_id: TEAM_ID,
                    group_type_index: GROUP_TYPE_INDEX,
                    group_key: GROUP_KEY,
                    group_properties: {},
                },
            ]
            mockPostgres.fetchGroupTypesByTeamIds.mockResolvedValue(expectedTypes)
            mockPostgres.fetchGroupsByKeys.mockResolvedValue(expectedGroups)
            mockGrpc.fetchGroupTypesByTeamIds.mockResolvedValue(expectedTypes)
            mockGrpc.fetchGroupsByKeys.mockResolvedValue(expectedGroups)

            // At 50% rollout, without sticky routing each call would independently
            // roll the dice and could split across backends. With sticky routing,
            // both calls within the same event loop iteration use the same decision.
            jest.spyOn(Math, 'random').mockReturnValue(0.3) // 0.3 * 100 = 30 < 50 → gRPC
            const repo = createRepo(50)

            await repo.fetchGroupTypesByTeamIds([TEAM_ID])
            await repo.fetchGroupsByKeys([TEAM_ID], [GROUP_TYPE_INDEX], [GROUP_KEY])

            // Both should hit gRPC, not a mix
            expect(mockGrpc.fetchGroupTypesByTeamIds).toHaveBeenCalled()
            expect(mockGrpc.fetchGroupsByKeys).toHaveBeenCalled()
            expect(mockPostgres.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
            expect(mockPostgres.fetchGroupsByKeys).not.toHaveBeenCalled()

            jest.spyOn(Math, 'random').mockRestore()
        })

        it('decision resets after setImmediate fires', async () => {
            mockPostgres.fetchGroupTypesByTeamIds.mockResolvedValue({})
            mockGrpc.fetchGroupTypesByTeamIds.mockResolvedValue({})

            const randomSpy = jest.spyOn(Math, 'random').mockReturnValue(0.3) // → gRPC at 50%
            const repo = createRepo(50)

            await repo.fetchGroupTypesByTeamIds([TEAM_ID])
            expect(mockGrpc.fetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)

            // Let setImmediate fire to clear the cached decision
            await new Promise((resolve) => setImmediate(resolve))

            // Now change the random to force postgres
            randomSpy.mockReturnValue(0.8) // 0.8 * 100 = 80 >= 50 → postgres

            await repo.fetchGroupTypesByTeamIds([TEAM_ID])
            expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)

            randomSpy.mockRestore()
        })
    })

    describe('write operations always delegate to postgres', () => {
        it('insertGroup', async () => {
            mockPostgres.insertGroup.mockResolvedValue(1)
            const repo = createRepo(100)
            const now = DateTime.utc()

            const result = await repo.insertGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { name: 'test' }, now, {}, {})

            expect(result).toBe(1)
            expect(mockPostgres.insertGroup).toHaveBeenCalledWith(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                { name: 'test' },
                now,
                {},
                {}
            )
        })

        it('updateGroup', async () => {
            mockPostgres.updateGroup.mockResolvedValue(2)
            const repo = createRepo(100)
            const now = DateTime.utc()

            const result = await repo.updateGroup(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                { name: 'updated' },
                now,
                {},
                {},
                'test-tag'
            )

            expect(result).toBe(2)
            expect(mockPostgres.updateGroup).toHaveBeenCalledWith(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                { name: 'updated' },
                now,
                {},
                {},
                'test-tag'
            )
        })

        it('updateGroupOptimistically', async () => {
            mockPostgres.updateGroupOptimistically.mockResolvedValue(3)
            const repo = createRepo(100)
            const now = DateTime.utc()

            const result = await repo.updateGroupOptimistically(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                1,
                { name: 'opt' },
                now,
                {},
                {}
            )

            expect(result).toBe(3)
            expect(mockPostgres.updateGroupOptimistically).toHaveBeenCalledWith(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                1,
                { name: 'opt' },
                now,
                {},
                {}
            )
        })

        it('insertGroupType', async () => {
            mockPostgres.insertGroupType.mockResolvedValue([0 as GroupTypeIndex, true])
            const repo = createRepo(100)

            const result = await repo.insertGroupType(TEAM_ID, PROJECT_ID, 'organization', 0)

            expect(result).toEqual([0, true])
            expect(mockPostgres.insertGroupType).toHaveBeenCalledWith(TEAM_ID, PROJECT_ID, 'organization', 0)
        })

        it('inTransaction', async () => {
            mockPostgres.inTransaction.mockImplementation((_desc, fn) => fn({} as any))
            const repo = createRepo(100)

            await repo.inTransaction('test', () => Promise.resolve('done'))

            expect(mockPostgres.inTransaction).toHaveBeenCalled()
        })
    })
})
