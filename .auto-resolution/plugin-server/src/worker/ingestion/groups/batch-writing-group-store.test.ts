// sort-imports-ignore
import { DateTime } from 'luxon'

import { Group, ProjectId, TeamId } from '../../../types'
import { DB } from '../../../utils/db/db'
import { MessageSizeTooLarge } from '../../../utils/db/error'
import { RaceConditionError } from '../../../utils/utils'

import { BatchWritingGroupStore, BatchWritingGroupStoreForBatch } from './batch-writing-group-store'
import { groupCacheOperationsCounter } from './metrics'
import { ClickhouseGroupRepository } from './repositories/clickhouse-group-repository'
import { GroupRepository } from './repositories/group-repository.interface'

// Mock the module before importing
jest.mock('../utils', () => ({
    captureIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

import { captureIngestionWarning } from '../utils'

// Mock the DB class

describe('BatchWritingGroupStore', () => {
    let db: DB
    let groupRepository: GroupRepository
    let groupStore: BatchWritingGroupStore
    let clickhouseGroupRepository: ClickhouseGroupRepository
    let teamId: TeamId
    let projectId: ProjectId
    let group: Group

    beforeEach(() => {
        teamId = 1
        projectId = 1 as ProjectId
        // Create a mock DB instance with all required methods
        group = {
            id: 1,
            team_id: teamId,
            group_type_index: 1,
            group_key: 'test',
            group_properties: { test: 'test' },
            created_at: DateTime.now(),
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
        }

        let dbCounter = 0
        db = {
            postgres: {},
        } as unknown as DB

        // Create a mock GroupRepository
        groupRepository = {
            fetchGroup: jest.fn().mockImplementation(() => {
                return Promise.resolve(group)
            }),
            insertGroup: jest.fn().mockImplementation(() => {
                return Promise.resolve(1)
            }),
            updateGroup: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            updateGroupOptimistically: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            inTransaction: jest.fn().mockImplementation(async (_description, transaction) => {
                // Create a proper mock transaction with the required methods
                const mockTransaction = {
                    fetchGroup: jest.fn().mockImplementation(() => {
                        return Promise.resolve(group)
                    }),
                    insertGroup: jest.fn().mockImplementation(() => {
                        return Promise.resolve(1)
                    }),
                    updateGroup: jest.fn().mockImplementation(() => {
                        dbCounter++
                        return Promise.resolve(dbCounter)
                    }),
                }
                return await transaction(mockTransaction)
            }),
        } as unknown as GroupRepository

        // Store the transaction mock for assertions
        ;(groupRepository as any).lastTransactionMock = null
        groupRepository.inTransaction = jest.fn().mockImplementation(async (_description, transaction) => {
            const mockTransaction = {
                fetchGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(group)
                }),
                insertGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(1)
                }),
                updateGroup: jest.fn().mockImplementation(() => {
                    dbCounter++
                    return Promise.resolve(dbCounter)
                }),
            }
            ;(groupRepository as any).lastTransactionMock = mockTransaction
            return await transaction(mockTransaction)
        })

        // Reset the counter before each test
        groupCacheOperationsCounter.reset()

        clickhouseGroupRepository = {
            upsertGroup: jest.fn().mockResolvedValue(undefined),
        } as unknown as ClickhouseGroupRepository
        groupStore = new BatchWritingGroupStore({
            db,
            groupRepository,
            clickhouseGroupRepository,
        })
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    it('should accumulate writes in cache, write once to db', async () => {
        const groupStoreForBatch = groupStore.forBatch()

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())
        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now())
        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { c: 'test' }, DateTime.now())

        await groupStoreForBatch.flush()

        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.insertGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0) // Uses optimistic update for existing groups
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            1,
            { a: 'test', b: 'test', c: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )

        const cacheMetrics = groupStoreForBatch.getCacheMetrics()

        expect(cacheMetrics.cacheHits).toBe(2)
        expect(cacheMetrics.cacheMisses).toBe(0)
    })

    it('should immediately write to db if new group', async () => {
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(undefined)
        const groupStoreForBatch = groupStore.forBatch()

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1)
        expect((groupRepository as any).lastTransactionMock.insertGroup).toHaveBeenCalledTimes(1)
    })

    it('should accumulate changes in cache after db write, even if new group', async () => {
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(undefined)
        const groupStoreForBatch = groupStore.forBatch()
        const createdAt = DateTime.now()

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, createdAt)
        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, createdAt)

        await groupStoreForBatch.flush()

        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1)
        expect((groupRepository as any).lastTransactionMock.insertGroup).toHaveBeenCalledTimes(1)

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            1,
            { a: 'test', b: 'test' },
            createdAt,
            {},
            {}
        )
    })

    it('should retry optimistic update if version mismatch', async () => {
        let fetchCounter = 0
        let updateCounter = 0
        jest.spyOn(groupRepository, 'fetchGroup').mockImplementation(() => {
            fetchCounter++
            if (fetchCounter === 1) {
                return Promise.resolve(group)
            } else {
                const updatedGroup = {
                    ...group,
                    version: fetchCounter,
                }
                return Promise.resolve(updatedGroup)
            }
        })
        jest.spyOn(groupRepository, 'updateGroupOptimistically').mockImplementation(() => {
            updateCounter++
            if (updateCounter < 3) {
                // Fail the first two updates
                return Promise.resolve(undefined)
            }
            return Promise.resolve(updateCounter)
        })

        const groupStoreForBatch = groupStore.forBatch()

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())
        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now())
        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { c: 'test' }, DateTime.now())

        await groupStoreForBatch.flush()

        // Should fetch 3 times, 1 for initial fetch, 2 for retries
        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(3)
        // Should make 3 updates, 2 failed, 1 successful
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(3)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0) // Uses optimistic updates, not transactions

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            3,
            { a: 'test', b: 'test', c: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )
    })

    it('should fall back to direct upsert if optimistic update fails', async () => {
        jest.spyOn(groupRepository, 'updateGroupOptimistically').mockResolvedValue(undefined)
        jest.spyOn(groupRepository, 'updateGroup').mockResolvedValue(2)
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(group)
        const groupStoreForBatch = groupStore.forBatch()

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'updated' }, DateTime.now())

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(clickhouseGroupRepository.upsertGroup).toHaveBeenCalledTimes(0)

        await groupStoreForBatch.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(5)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1)
        expect((groupRepository as any).lastTransactionMock.updateGroup).toHaveBeenCalledTimes(1)
        expect(clickhouseGroupRepository.upsertGroup).toHaveBeenCalledTimes(1)
    })

    it('should share cache between distinct ids', async () => {
        const groupStoreForBatch = groupStore.forBatch()

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())
        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now())

        await groupStoreForBatch.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0) // Uses optimistic update for existing groups
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            1,
            { a: 'test', b: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )
    })

    it('should not write to db if no properties are changed', async () => {
        const groupStoreForBatch = groupStore.forBatch()

        // Mock the groupRepository.fetchGroup to return a group with the same properties
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(group)

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', group.group_properties, DateTime.now())

        await groupStoreForBatch.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0)
        // No transaction calls expected since no properties changed
    })

    it('should capture warning and stop retrying if message size too large', async () => {
        // we need to mock the clickhouse repository upsertGroup method
        clickhouseGroupRepository.upsertGroup = jest
            .fn()
            .mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

        const groupStoreForBatch = groupStore.forBatch()

        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

        await groupStoreForBatch.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0)
        // No transaction calls expected since optimistic update failed
        expect(captureIngestionWarning).toHaveBeenCalledTimes(1)
    })

    it('should retry on race condition error and clear cache', async () => {
        let insertCounter = 0
        let fetchCounter = 0
        jest.spyOn(groupRepository, 'fetchGroup').mockImplementation(() => {
            fetchCounter++
            if (fetchCounter === 1) {
                return Promise.resolve(undefined)
            } else {
                return Promise.resolve(group)
            }
        })

        // Override the transaction mock to throw on first insertGroup call
        groupRepository.inTransaction = jest.fn().mockImplementation(async (description, transaction) => {
            const mockTransaction = {
                fetchGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(group)
                }),
                insertGroup: jest.fn().mockImplementation(() => {
                    insertCounter++
                    if (insertCounter === 1) {
                        throw new RaceConditionError('Parallel posthog_group inserts, retry')
                    }
                    return Promise.resolve(1)
                }),
                updateGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(1)
                }),
            }
            ;(groupRepository as any).lastTransactionMock = mockTransaction
            return await transaction(mockTransaction)
        })

        const groupStoreForBatch = groupStore.forBatch()

        // track cache delete
        const groupCache = (groupStoreForBatch as BatchWritingGroupStoreForBatch).getGroupCache()
        const cacheDeleteSpy = jest.spyOn(groupCache, 'delete')

        // Add to cache to verify it gets cleared on race condition
        await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

        await groupStoreForBatch.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(2) // Once for initial fetch, once for retry
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1) // Once for initial insert, once for retry (new group)
        expect((groupRepository as any).lastTransactionMock.insertGroup).toHaveBeenCalledTimes(1)

        expect(cacheDeleteSpy).toHaveBeenCalledWith(teamId, 'test')

        // Final call should succeed
        expect(groupRepository.updateGroupOptimistically).toHaveBeenLastCalledWith(
            teamId,
            1,
            'test',
            1, // version from second fetch
            { a: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )
    })
})
