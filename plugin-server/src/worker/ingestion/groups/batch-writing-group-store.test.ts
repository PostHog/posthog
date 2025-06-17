import { DateTime } from 'luxon'

import { Group, ProjectId, TeamId } from '../../../types'
import { DB } from '../../../utils/db/db'
import { MessageSizeTooLarge } from '../../../utils/db/error'
import { BatchWritingGroupStore } from './batch-writing-group-store'
import { groupCacheOperationsCounter } from './metrics'

// Mock the utils module
jest.mock('../utils', () => ({
    captureIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

// Import the mocked function
import { captureIngestionWarning } from '../utils'

// Mock the DB class

describe('BatchWritingGroupStore', () => {
    let db: DB
    let groupStore: BatchWritingGroupStore
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
            postgres: {
                transaction: jest.fn().mockImplementation(async (_usage, _tag, transaction) => {
                    return await transaction()
                }),
            },
            fetchGroup: jest.fn().mockImplementation(() => {
                return Promise.resolve(group)
            }),
            updateGroup: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            insertGroup: jest.fn().mockImplementation(() => {
                return Promise.resolve(1)
            }),
            updateGroupOptimistically: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            upsertGroupClickhouse: jest.fn(),
        } as unknown as DB

        // Reset the counter before each test
        groupCacheOperationsCounter.reset()
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('Batch Writing Disabled', () => {
        beforeEach(() => {
            groupStore = new BatchWritingGroupStore(db)
        })

        it('should fetch group from db multiple times, write multiple times to db', async () => {
            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now(), false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now(), false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { c: 'test' }, DateTime.now(), false)

            expect(db.postgres.transaction).toHaveBeenCalledTimes(3)
            expect(db.fetchGroup).toHaveBeenCalledTimes(3)
            expect(db.updateGroup).toHaveBeenCalledTimes(3)

            const cacheMetrics = groupStoreForBatch.getCacheMetrics()

            // Validate cache operations counter
            expect(cacheMetrics.cacheHits).toBe(0)
            expect(cacheMetrics.cacheMisses).toBe(0)
        })

        it('should insert group if does not exist in postgres', async () => {
            jest.spyOn(db, 'fetchGroup').mockResolvedValue(undefined)
            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now(), false)

            expect(db.fetchGroup).toHaveBeenCalledTimes(1)
            expect(db.insertGroup).toHaveBeenCalledTimes(1)
        })
    })

    describe('Batch Writing Enabled', () => {
        beforeEach(() => {
            groupStore = new BatchWritingGroupStore(db, { batchWritingEnabled: true })
        })

        it('should accumulate writes in cache, write once to db', async () => {
            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now(), false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now(), false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { c: 'test' }, DateTime.now(), false)

            await groupStoreForBatch.flush()

            expect(db.fetchGroup).toHaveBeenCalledTimes(1)
            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(db.updateGroup).toHaveBeenCalledTimes(0)
            expect(db.insertGroup).toHaveBeenCalledTimes(0)
            expect(db.updateGroupOptimistically).toHaveBeenCalledWith(
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
            jest.spyOn(db, 'fetchGroup').mockResolvedValue(undefined)
            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now(), false)

            expect(db.fetchGroup).toHaveBeenCalledTimes(1)
            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(0)
            expect(db.updateGroup).toHaveBeenCalledTimes(0)
            expect(db.insertGroup).toHaveBeenCalledTimes(1)
        })

        it('should accumulate changes in cache after db write, even if new group', async () => {
            jest.spyOn(db, 'fetchGroup').mockResolvedValue(undefined)
            const groupStoreForBatch = groupStore.forBatch()
            const createdAt = DateTime.now()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, createdAt, false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, createdAt, false)

            await groupStoreForBatch.flush()

            expect(db.fetchGroup).toHaveBeenCalledTimes(1)
            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(db.updateGroup).toHaveBeenCalledTimes(0)
            expect(db.insertGroup).toHaveBeenCalledTimes(1)

            expect(db.updateGroupOptimistically).toHaveBeenCalledWith(
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
            jest.spyOn(db, 'fetchGroup').mockImplementation(() => {
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
            jest.spyOn(db, 'updateGroupOptimistically').mockImplementation(() => {
                updateCounter++
                if (updateCounter < 3) {
                    // Fail the first two updates
                    return Promise.resolve(undefined)
                }
                return Promise.resolve(updateCounter)
            })

            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now(), false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now(), false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { c: 'test' }, DateTime.now(), false)

            await groupStoreForBatch.flush()

            // Should fetch 3 times, 1 for initial fetch, 2 for retries
            expect(db.fetchGroup).toHaveBeenCalledTimes(3)
            // Should make 3 updates, 2 failed, 1 successful
            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(3)
            expect(db.updateGroup).toHaveBeenCalledTimes(0)

            expect(db.updateGroupOptimistically).toHaveBeenCalledWith(
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
            jest.spyOn(db, 'updateGroupOptimistically').mockResolvedValue(undefined)
            jest.spyOn(db, 'updateGroup').mockResolvedValue(2)
            jest.spyOn(db, 'fetchGroup').mockResolvedValue(group)
            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'updated' }, DateTime.now(), false)

            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(0)
            expect(db.updateGroup).toHaveBeenCalledTimes(0)
            expect(db.upsertGroupClickhouse).toHaveBeenCalledTimes(0)

            await groupStoreForBatch.flush()

            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(5)
            expect(db.updateGroup).toHaveBeenCalledTimes(1)
            expect(db.upsertGroupClickhouse).toHaveBeenCalledTimes(1)
        })

        it('should share cache between distinct ids', async () => {
            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now(), false)
            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now(), false)

            await groupStoreForBatch.flush()

            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(db.updateGroupOptimistically).toHaveBeenCalledWith(
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

            // Mock the db.fetchGroup to return a group with the same properties
            jest.spyOn(db, 'fetchGroup').mockResolvedValue(group)

            await groupStoreForBatch.upsertGroup(
                teamId,
                projectId,
                1,
                'test',
                group.group_properties,
                DateTime.now(),
                false
            )

            await groupStoreForBatch.flush()

            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(0)
            expect(db.updateGroup).toHaveBeenCalledTimes(0)
            expect(db.insertGroup).toHaveBeenCalledTimes(0)
        })

        it('should capture warning and stop retrying if message size too large', async () => {
            // we need to mock the kafka producer queueMessages method
            db.upsertGroupClickhouse = jest.fn().mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

            const groupStoreForBatch = groupStore.forBatch()

            await groupStoreForBatch.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now(), false)

            await groupStoreForBatch.flush()

            expect(db.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(db.updateGroup).toHaveBeenCalledTimes(0)
            expect(db.insertGroup).toHaveBeenCalledTimes(0)
            expect(captureIngestionWarning).toHaveBeenCalledTimes(1)
        })
    })
})
