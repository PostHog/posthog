import { DateTime } from 'luxon'

import { InternalPerson, TeamId } from '~/types'
import { DB } from '~/utils/db/db'
import { MessageSizeTooLarge } from '~/utils/db/error'

import { captureIngestionWarning } from '../utils'
import { BatchWritingPersonsStore, BatchWritingPersonsStoreForBatch } from './batch-writing-person-store'
import { fromInternalPerson } from './person-update-batch'

// Mock the utils module
jest.mock('../utils', () => ({
    captureIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

// Mock metrics
jest.mock('./metrics', () => ({
    observeLatencyByVersion: jest.fn(),
    personCacheOperationsCounter: { inc: jest.fn() },
    personCacheSizeHistogram: { observe: jest.fn() },
    personDatabaseOperationsPerBatchHistogram: { observe: jest.fn() },
    personFallbackOperationsCounter: { inc: jest.fn() },
    personFetchForCheckingCacheOperationsCounter: { inc: jest.fn() },
    personFetchForUpdateCacheOperationsCounter: { inc: jest.fn() },
    personFlushBatchSizeHistogram: { observe: jest.fn() },
    personFlushLatencyHistogram: { observe: jest.fn() },
    personFlushOperationsCounter: { inc: jest.fn() },
    personMethodCallsPerBatchHistogram: { observe: jest.fn() },
    personOptimisticUpdateConflictsPerBatchCounter: { inc: jest.fn() },
    personPropertyKeyUpdateCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personRetryAttemptsHistogram: { observe: jest.fn() },
    personWriteMethodAttemptCounter: { inc: jest.fn() },
    personWriteMethodLatencyHistogram: { observe: jest.fn() },
    totalPersonUpdateLatencyPerBatchHistogram: { observe: jest.fn() },
}))

describe('BatchWritingPersonStore', () => {
    let db: DB
    let personStore: BatchWritingPersonsStore
    let teamId: TeamId
    let person: InternalPerson

    beforeEach(() => {
        teamId = 1
        person = {
            id: '1',
            team_id: teamId,
            properties: {
                test: 'test',
            },
            created_at: DateTime.now(),
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
            is_user_id: null,
            is_identified: false,
            uuid: '1',
        }

        let dbCounter = 0
        db = {
            postgres: {
                transaction: jest.fn().mockImplementation(async (_usage, _tag, transaction) => {
                    return await transaction(transaction)
                }),
            },
            fetchPerson: jest.fn().mockImplementation(() => {
                return Promise.resolve(person)
            }),
            createPerson: jest.fn().mockImplementation(() => {
                dbCounter++
                const personCopy = { ...person, version: dbCounter }
                return Promise.resolve([personCopy, []])
            }),
            updatePerson: jest.fn().mockImplementation(() => {
                dbCounter++
                const personCopy = { ...person, version: dbCounter }
                return Promise.resolve([personCopy, []])
            }),
            updatePersonAssertVersion: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter) // Return new version number
            }),
            deletePerson: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
            moveDistinctIds: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
        } as unknown as DB

        personStore = new BatchWritingPersonsStore(db)
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    const getBatchStoreForBatch = () => personStore.forBatch() as BatchWritingPersonsStoreForBatch

    it('should update person in cache', async () => {
        const personStoreForBatch = getBatchStoreForBatch()
        const response = await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_value: 'new_value' },
            [],
            {},
            'test'
        )
        expect(response).toEqual([
            { ...person, version: 1, properties: { test: 'test', new_value: 'new_value' } },
            [],
            false,
        ])

        // Validate cache - should contain a PersonUpdate object
        const cache = (personStoreForBatch as any)['personUpdateCache']
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)
        expect(cachedUpdate).toBeDefined()
        expect(cachedUpdate.distinct_id).toBe('test')
        expect(cachedUpdate.needs_write).toBe(true)
        expect(cachedUpdate.properties).toEqual({ test: 'test' }) // Original properties from database
        expect(cachedUpdate.properties_to_set).toEqual({ new_value: 'new_value' }) // New properties to set
        expect(cachedUpdate.properties_to_unset).toEqual([]) // No properties to unset
        expect(cachedUpdate.team_id).toBe(1)
        expect(cachedUpdate.id).toBe('1')
    })

    it('should handle unsetting properties', async () => {
        const personStoreForBatch = getBatchStoreForBatch()
        const response = await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            {
                value_to_unset: 'value_to_unset',
            },
            [],
            {},
            'test'
        )
        expect(response).toEqual([
            { ...person, version: 1, properties: { test: 'test', value_to_unset: 'value_to_unset' } },
            [],
            false,
        ])

        const response2 = await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            {},
            ['value_to_unset'],
            {},
            'test'
        )
        expect(response2).toEqual([{ ...person, version: 1, properties: { test: 'test' } }, [], false])

        // Check cache contains merged updates
        const cache = personStoreForBatch.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties).toEqual({ test: 'test' })
        expect(cachedUpdate.properties_to_set).toEqual({ test: 'test', value_to_unset: 'value_to_unset' })
        expect(cachedUpdate.properties_to_unset).toEqual(['value_to_unset']) // No properties to unset
        expect(cachedUpdate.needs_write).toBe(true)

        await personStoreForBatch.flush()

        expect(db.updatePerson).toHaveBeenCalledWith(
            expect.objectContaining({
                properties: { test: 'test' },
            }),
            expect.anything(),
            undefined,
            'updatePersonNoAssert'
        )
    })

    it('should remove person from caches when deleted', async () => {
        const personStoreForBatch = getBatchStoreForBatch()

        // Add person to cache using the proper PersonUpdate structure
        let updateCache = personStoreForBatch.getUpdateCache()
        const personUpdate = fromInternalPerson(person, 'test')
        personUpdate.properties = { new_value: 'new_value' }
        personUpdate.needs_write = false
        updateCache.set(`${teamId}:${person.id}`, personUpdate)

        let checkCache = personStoreForBatch.getCheckCache()
        checkCache.set(`${teamId}:test`, person)

        personStoreForBatch.setDistinctIdToPersonId(teamId, 'test', person.id)

        const response = await personStoreForBatch.deletePerson(person, 'test')
        expect(response).toEqual([])

        // Validate cache
        updateCache = personStoreForBatch.getUpdateCache()
        checkCache = personStoreForBatch.getCheckCache()
        expect(updateCache.get(`${teamId}:${person.id}`)).toBeUndefined()
        expect(checkCache.get(`${teamId}:${person.id}`)).toBeUndefined()
    })

    it('should flush person updates with default NO_ASSERT mode', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Add a person update to cache
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_value: 'new_value' },
            [],
            {},
            'test'
        )

        // Flush should call updatePerson (NO_ASSERT default mode)
        await personStoreForBatch.flush()

        expect(db.updatePerson).toHaveBeenCalledTimes(1)
        expect(db.updatePersonAssertVersion).not.toHaveBeenCalled()
    })

    it('should fallback to direct update when optimistic update fails', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })
        const personStoreForBatch = assertVersionStore.forBatch()

        // Mock optimistic update to fail (version mismatch)
        db.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []])

        // Add a person update to cache
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_value: 'new_value' },
            [],
            {},
            'test'
        )

        // Flush should retry optimistically then fallback to direct update
        await personStoreForBatch.flush()

        expect(db.updatePersonAssertVersion).toHaveBeenCalled()
        expect(db.fetchPerson).toHaveBeenCalled() // Called during conflict resolution
        expect(db.updatePerson).toHaveBeenCalled() // Fallback
    })

    it('should merge multiple updates for same person', async () => {
        const personStoreForBatch = getBatchStoreForBatch()

        // First update
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(person, { prop1: 'value1' }, [], {}, 'test')

        // Second update to same person
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { test: 'value2', prop2: 'value2' },
            [],
            {},
            'test'
        )

        // Check cache contains merged updates
        const cache = personStoreForBatch.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties).toEqual({ test: 'test' }) // Original properties from database
        expect(cachedUpdate.properties_to_set).toEqual({ prop1: 'value1', test: 'value2', prop2: 'value2' }) // Merged properties to set
        expect(cachedUpdate.properties_to_unset).toEqual([]) // No properties to unset
        expect(cachedUpdate.needs_write).toBe(true)
    })

    describe('fetchForUpdate vs fetchForChecking', () => {
        it('should use separate caches for update and checking', async () => {
            const personStoreForBatch = getBatchStoreForBatch()

            // Fetch for checking should cache in check cache
            const personFromCheck = await personStoreForBatch.fetchForChecking(teamId, 'test-distinct')
            expect(personFromCheck).toEqual(person)

            const checkCache = (personStoreForBatch as any)['personCheckCache']
            expect(checkCache.get('1:test-distinct')).toEqual(person)

            // Fetch for update should cache in update cache and return PersonUpdate converted to InternalPerson
            const personFromUpdate = await personStoreForBatch.fetchForUpdate(teamId, 'test-distinct2')
            expect(personFromUpdate).toBeDefined()
            expect(personFromUpdate!.id).toBe(person.id)
            expect(personFromUpdate!.team_id).toBe(person.team_id)
            expect(personFromUpdate!.id).toBe(person.id)

            const updateCache = personStoreForBatch.getUpdateCache()
            const cachedPersonUpdate = updateCache.get(`${teamId}:${person.id}`)
            expect(cachedPersonUpdate).toBeDefined()
            expect(cachedPersonUpdate!.distinct_id).toBe('test-distinct2')
        })

        it('should handle cache hits for both checking and updating', async () => {
            const personStoreForBatch = personStore.forBatch()

            // First fetch should hit the database
            await personStoreForBatch.fetchForChecking(teamId, 'test-distinct')
            expect(db.fetchPerson).toHaveBeenCalledTimes(1)

            // Second fetch should hit the cache
            await personStoreForBatch.fetchForChecking(teamId, 'test-distinct')
            expect(db.fetchPerson).toHaveBeenCalledTimes(1) // No additional call

            // Similar for update cache
            await personStoreForBatch.fetchForUpdate(teamId, 'test-distinct2')
            expect(db.fetchPerson).toHaveBeenCalledTimes(2)

            await personStoreForBatch.fetchForUpdate(teamId, 'test-distinct2')
            expect(db.fetchPerson).toHaveBeenCalledTimes(2) // No additional call
        })

        it('should prefer update cache over check cache in fetchForChecking', async () => {
            const personStoreForBatch = personStore.forBatch()

            // First populate update cache
            await personStoreForBatch.fetchForUpdate(teamId, 'test-distinct')

            // Reset the mock to track new calls
            jest.clearAllMocks()

            // fetchForChecking should use the cached PersonUpdate instead of hitting DB
            const result = await personStoreForBatch.fetchForChecking(teamId, 'test-distinct')
            expect(result).toBeDefined()
            expect(db.fetchPerson).not.toHaveBeenCalled()
        })

        it('should handle null results from database', async () => {
            const personStoreForBatch = personStore.forBatch()
            db.fetchPerson = jest.fn().mockResolvedValue(undefined)

            const checkResult = await personStoreForBatch.fetchForChecking(teamId, 'nonexistent')
            expect(checkResult).toBeNull()

            const updateResult = await personStoreForBatch.fetchForUpdate(teamId, 'nonexistent')
            expect(updateResult).toBeNull()
        })
    })

    it('should retry optimistic updates with exponential backoff', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })
        const personStoreForBatch = assertVersionStore.forBatch()
        let callCount = 0

        // Mock to fail first few times, then succeed
        db.updatePersonAssertVersion = jest.fn().mockImplementation(() => {
            callCount++
            if (callCount < 3) {
                return Promise.resolve([undefined, []]) // version mismatch
            }
            return Promise.resolve([5, []]) // success on 3rd try
        })

        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_value: 'new_value' },
            [],
            {},
            'test'
        )
        await personStoreForBatch.flush()

        expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(3)
        expect(db.fetchPerson).toHaveBeenCalledTimes(2) // Called for each conflict
        expect(db.updatePerson).not.toHaveBeenCalled() // Shouldn't fallback if retries succeed
    })

    it('should fallback to direct update after max retries', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })
        const personStoreForBatch = assertVersionStore.forBatch()

        // Mock to always fail optimistic updates
        db.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []])

        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_value: 'new_value' },
            [],
            {},
            'test'
        )
        await personStoreForBatch.flush()

        // Should try optimistic update multiple times based on config
        expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(5) // default max retries
        expect(db.updatePerson).toHaveBeenCalledTimes(1) // fallback
    })

    it('should merge properties during conflict resolution', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })
        const personStoreForBatch = assertVersionStore.forBatch()
        const latestPerson = {
            ...person,
            version: 3,
            properties: { existing_prop: 'existing_value', shared_prop: 'old_value' },
        }

        db.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []]) // Always fail, but we don't care about the version
        db.fetchPerson = jest.fn().mockResolvedValue(latestPerson)

        // Update with new properties
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_prop: 'new_value', shared_prop: 'new_value' },
            [],
            {},
            'test'
        )

        await personStoreForBatch.flush()

        // Verify the direct update was called with merged properties
        expect(db.updatePerson).toHaveBeenCalledWith(
            expect.objectContaining({
                version: 3, // Should use latest version
            }),
            expect.objectContaining({
                properties: {
                    existing_prop: 'existing_value',
                    new_prop: 'new_value',
                    shared_prop: 'new_value',
                },
            }),
            undefined,
            'updatePersonNoAssert'
        )
    })

    it('should handle database errors gracefully during flush', async () => {
        const personStoreForBatch = personStore.forBatch()

        db.updatePerson = jest.fn().mockRejectedValue(new Error('Database connection failed'))

        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_value: 'new_value' },
            [],
            {},
            'test'
        )

        await expect(personStoreForBatch.flush()).rejects.toThrow('Database connection failed')
    })

    it('should handle partial failures in batch flush', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Set up multiple updates
        const person2 = { ...person, id: '2', uuid: '2' }
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(person, { test: 'value1' }, [], {}, 'test1')
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(person2, { test: 'value2' }, [], {}, 'test2')

        // Mock first update to succeed, second to fail
        let callCount = 0
        db.updatePerson = jest.fn().mockImplementation(() => {
            callCount++
            if (callCount === 1) {
                return Promise.resolve([person, []]) // success for first person
            }
            throw new Error('Database error') // fail for second person
        })

        await expect(personStoreForBatch.flush()).rejects.toThrow('Database error')
    })

    it('should handle clearing cache for different team IDs', async () => {
        const personStoreForBatch = getBatchStoreForBatch()
        const person2 = { ...person, id: 'person2-id', uuid: 'person2-uuid', team_id: 2 }

        // Add to both caches for different teams
        const updateCache = personStoreForBatch.getUpdateCache()
        const checkCache = personStoreForBatch.getCheckCache()

        updateCache.set(`${person.team_id}:${person.id}`, fromInternalPerson(person, 'test'))
        updateCache.set(`${person2.team_id}:${person2.id}`, fromInternalPerson(person2, 'test'))
        checkCache.set(`${person.team_id}:test`, person)
        checkCache.set(`${person2.team_id}:test`, person2)
        personStoreForBatch.setDistinctIdToPersonId(person.team_id, 'test', person.id)
        personStoreForBatch.setDistinctIdToPersonId(person2.team_id, 'test', person2.id)

        // Delete person from team 1
        await personStoreForBatch.deletePerson(person, 'test')

        // Only team 1 entries should be removed
        expect(updateCache.has(`${person.team_id}:${person.id}`)).toBe(false)
        expect(updateCache.has(`${person2.team_id}:${person2.id}`)).toBe(true)
        expect(checkCache.has(`${person.team_id}:test`)).toBe(false)
        expect(checkCache.has(`${person2.team_id}:test`)).toBe(true)
    })

    it('should handle empty properties updates', async () => {
        const personStoreForBatch = getBatchStoreForBatch()

        const result = await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(person, {}, [], {}, 'test')
        expect(result[0]).toEqual(person) // Should return original person unchanged

        const cache = personStoreForBatch.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.needs_write).toBe(true) // Still marked for write
    })

    it('should handle null and undefined property values', async () => {
        const personStoreForBatch = getBatchStoreForBatch()

        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { null_prop: null, undefined_prop: undefined },
            [],
            {},
            'test'
        )

        const cache = personStoreForBatch.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties_to_set.null_prop).toBeNull()
        expect(cachedUpdate.properties_to_set.undefined_prop).toBeUndefined()

        await personStoreForBatch.flush()

        expect(db.updatePerson).toHaveBeenCalledWith(
            expect.objectContaining({
                properties: { null_prop: null, undefined_prop: undefined, test: 'test' },
            }),
            expect.anything(),
            undefined,
            'updatePersonNoAssert'
        )
    })

    it('should handle MessageSizeTooLarge errors and capture warning', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Mock NO_ASSERT update to fail with MessageSizeTooLarge
        db.updatePerson = jest.fn().mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

        // Add a person update to cache
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_value: 'new_value' },
            [],
            {},
            'test'
        )

        // Flush should handle the error and capture warning
        await personStoreForBatch.flush()

        expect(db.updatePerson).toHaveBeenCalled()
        expect(captureIngestionWarning).toHaveBeenCalledWith(
            db.kafkaProducer,
            teamId,
            'person_upsert_message_size_too_large',
            {
                personId: person.id,
                distinctId: 'test',
            }
        )
    })

    describe('dbWriteMode functionality', () => {
        describe('flush with NO_ASSERT mode', () => {
            it('should call updatePersonNoAssert directly without retries', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'NO_ASSERT' })
                const personStoreForBatch = personStore.forBatch()

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.updatePerson).toHaveBeenCalledTimes(1)
                expect(db.updatePersonAssertVersion).not.toHaveBeenCalled()
                expect(db.postgres.transaction).not.toHaveBeenCalled()
            })

            it('should handle errors in NO_ASSERT mode without fallback', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'NO_ASSERT' })
                const personStoreForBatch = personStore.forBatch()

                db.updatePerson = jest.fn().mockRejectedValue(new Error('Database error'))

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )

                await expect(personStoreForBatch.flush()).rejects.toThrow('Database error')
                expect(db.updatePerson).toHaveBeenCalledTimes(6) // 5 for update, 1 for fallback
                expect(db.updatePersonAssertVersion).not.toHaveBeenCalled()
            })
        })

        describe('flush with ASSERT_VERSION mode', () => {
            it('should call updatePersonAssertVersion with retries', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })
                const personStoreForBatch = personStore.forBatch()

                db.updatePersonAssertVersion = jest.fn().mockResolvedValue([5, []]) // success

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(1)
                expect(db.updatePerson).not.toHaveBeenCalled()
                expect(db.postgres.transaction).not.toHaveBeenCalled()
            })

            it('should retry on version conflicts and eventually fallback', async () => {
                const personStore = new BatchWritingPersonsStore(db, {
                    dbWriteMode: 'ASSERT_VERSION',
                    maxOptimisticUpdateRetries: 2,
                })
                const personStoreForBatch = personStore.forBatch()

                // Mock to always fail optimistic updates
                db.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []])

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(2) // retries
                expect(db.updatePerson).toHaveBeenCalledTimes(1) // fallback
            })

            it('should handle MessageSizeTooLarge in ASSERT_VERSION mode', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })
                const personStoreForBatch = personStore.forBatch()

                db.updatePersonAssertVersion = jest
                    .fn()
                    .mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.updatePersonAssertVersion).toHaveBeenCalled()
                expect(captureIngestionWarning).toHaveBeenCalledWith(
                    db.kafkaProducer,
                    teamId,
                    'person_upsert_message_size_too_large',
                    {
                        personId: person.id,
                        distinctId: 'test',
                    }
                )
                expect(db.updatePerson).not.toHaveBeenCalled() // No fallback for MessageSizeTooLarge
            })
        })

        describe('flush with WITH_TRANSACTION mode', () => {
            it('should call updatePersonWithTransaction directly without optimistic updates', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'WITH_TRANSACTION' })
                const personStoreForBatch = personStore.forBatch()

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.postgres.transaction).toHaveBeenCalledTimes(1)
                expect(db.updatePersonAssertVersion).not.toHaveBeenCalled()
                expect(db.updatePerson).toHaveBeenCalledWith(
                    expect.any(Object),
                    expect.any(Object),
                    expect.anything(), // tx
                    'forUpdate'
                )
            })

            it('should retry WITH_TRANSACTION on failures', async () => {
                const personStore = new BatchWritingPersonsStore(db, {
                    dbWriteMode: 'WITH_TRANSACTION',
                    maxOptimisticUpdateRetries: 2,
                })
                const personStoreForBatch = personStore.forBatch()

                let callCount = 0
                db.postgres.transaction = jest.fn().mockImplementation(async (_usage, _tag, transactionCallback) => {
                    callCount++
                    if (callCount < 2) {
                        throw new Error('Transaction failed')
                    }
                    return await transactionCallback({}) // success on second try
                })

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.postgres.transaction).toHaveBeenCalledTimes(2)
                expect(db.updatePersonAssertVersion).not.toHaveBeenCalled()
            })

            it('should handle MessageSizeTooLarge in WITH_TRANSACTION mode', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'WITH_TRANSACTION' })
                const personStoreForBatch = personStore.forBatch()

                db.postgres.transaction = jest
                    .fn()
                    .mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(captureIngestionWarning).toHaveBeenCalledWith(
                    db.kafkaProducer,
                    teamId,
                    'person_upsert_message_size_too_large',
                    {
                        personId: person.id,
                        distinctId: 'test',
                    }
                )
                expect(db.postgres.transaction).toHaveBeenCalled()
            })

            it('should fallback to updatePersonNoAssert after max retries', async () => {
                const personStore = new BatchWritingPersonsStore(db, {
                    dbWriteMode: 'WITH_TRANSACTION',
                    maxOptimisticUpdateRetries: 2,
                })
                const personStoreForBatch = personStore.forBatch()

                // Mock transaction to always fail
                db.postgres.transaction = jest.fn().mockRejectedValue(new Error('Transaction failed'))

                await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.postgres.transaction).toHaveBeenCalledTimes(2)
                expect(db.updatePersonAssertVersion).not.toHaveBeenCalled()
                expect(db.updatePerson).toHaveBeenCalledTimes(1)
            })
        })

        describe('concurrent updates with different dbWriteModes', () => {
            it('should handle multiple updates with different modes correctly', async () => {
                const noAssertStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'NO_ASSERT' })
                const assertVersionStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })

                const noAssertBatch = noAssertStore.forBatch()
                const assertVersionBatch = assertVersionStore.forBatch()

                const person2 = { ...person, id: '2', uuid: '2' }

                // Mock successful updates
                db.updatePersonAssertVersion = jest.fn().mockResolvedValue([5, []])

                await Promise.all([
                    noAssertBatch.updatePersonWithPropertiesDiffForUpdate(
                        person,
                        { mode: 'no_assert' },
                        [],
                        {},
                        'test1'
                    ),
                    assertVersionBatch.updatePersonWithPropertiesDiffForUpdate(
                        person2,
                        { mode: 'assert_version' },
                        [],
                        {},
                        'test2'
                    ),
                ])

                await Promise.all([noAssertBatch.flush(), assertVersionBatch.flush()])

                expect(db.updatePerson).toHaveBeenCalledTimes(1) // NO_ASSERT mode
                expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(1) // ASSERT_VERSION mode
            })
        })
    })

    it('should handle concurrent updates with ASSERT_VERSION mode and preserve both properties', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(db, {
            dbWriteMode: 'ASSERT_VERSION',
        })
        const personStoreForBatch = assertVersionStore.forBatch()

        // Initial person in database with 2 properties
        const initialPerson = {
            ...person,
            version: 1,
            properties: {
                existing_prop1: 'initial_value1',
                existing_prop2: 'initial_value2',
            },
        }

        // Simulate that another pod directly writes to the database
        // This increases the version and updates one property
        const updatedByOtherPod = {
            ...initialPerson,
            version: 2,
            properties: {
                existing_prop1: 'updated_by_other_pod',
                existing_prop2: 'initial_value2', // This property stays the same
            },
        }

        // Mock optimistic update to fail on first try, succeed on retry
        // Completely replace the mock from beforeEach
        db.updatePersonAssertVersion = jest
            .fn()
            .mockResolvedValueOnce([undefined, []]) // First call fails (version mismatch)
            .mockResolvedValueOnce([3, []]) // Second call succeeds with new version

        // Mock fetchPerson to return the updated person when called during conflict resolution
        db.fetchPerson = jest.fn().mockResolvedValue(updatedByOtherPod)

        // Process an event that will override one of the properties
        // We pass the initial person directly, so no initial fetch is needed
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            initialPerson,
            { existing_prop2: 'updated_by_this_pod' },
            [],
            {},
            'test'
        )

        // Flush should trigger optimistic update, fail, then merge and retry
        await personStoreForBatch.flush()

        // Verify the optimistic update was attempted (should be called twice: once initially, once on retry)
        expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(2)

        // Verify fetchPerson was called once during conflict resolution
        expect(db.fetchPerson).toHaveBeenCalledTimes(1)

        // Since the second retry succeeds, there should be no fallback to updatePerson
        expect(db.updatePerson).not.toHaveBeenCalled()

        // Verify the second call to updatePersonAssertVersion had the merged properties
        expect(db.updatePersonAssertVersion).toHaveBeenLastCalledWith(
            expect.objectContaining({
                version: 3, // Should use the latest version from the database
                properties: {
                    existing_prop1: 'updated_by_other_pod', // Preserved from other pod's update
                    existing_prop2: 'updated_by_this_pod', // Updated by this pod
                },
                properties_to_set: {
                    existing_prop2: 'updated_by_this_pod', // Only the changed property should be in properties_to_set
                },
                properties_to_unset: [], // No properties to unset
            })
        )
    })

    it('should consolidate updates for same person via different distinct IDs', async () => {
        // This test validates that when two distinct IDs point to the same person,
        // updates via both distinct IDs should be merged into a single person update
        const personStoreForBatch = getBatchStoreForBatch()

        const distinctId1 = 'user-email@example.com'
        const distinctId2 = 'user-device-abc123'

        // Both distinct IDs point to the same person
        const sharedPerson = {
            ...person,
            properties: {
                initial_prop: 'initial_value',
            },
        }

        // Mock fetchPerson to return the same person for both distinct IDs
        db.fetchPerson = jest.fn().mockImplementation(() => {
            return Promise.resolve(sharedPerson)
        })

        // Update via first distinct ID
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            { prop_from_distinctId1: 'value1' },
            [],
            {},
            distinctId1
        )

        // Update via second distinct ID
        await personStoreForBatch.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            { prop_from_distinctId2: 'value2' },
            [],
            {},
            distinctId2
        )

        const cache = personStoreForBatch.getUpdateCache()

        const cacheKey = `${teamId}:${sharedPerson.id}`
        const cacheValue = cache.get(cacheKey)
        // Currently both cache entries exist, which is the problem
        expect(cacheValue).toBeDefined()

        // Both cache entries have the same person id but different properties
        expect(cacheValue?.id).toBe(sharedPerson.id)
        expect(cacheValue?.properties).toEqual({
            initial_prop: 'initial_value',
        }) // Original properties from database
        expect(cacheValue?.properties_to_set).toEqual({
            initial_prop: 'initial_value',
            prop_from_distinctId1: 'value1',
            prop_from_distinctId2: 'value2',
        }) // Properties to set
        expect(cacheValue?.properties_to_unset).toEqual([]) // Properties to unset

        expect(cache.size).toBe(1)

        // Flush should consolidate these into a single DB update
        await personStoreForBatch.flush()

        // ISSUE: Currently this will likely result in 2 separate DB calls for the same person
        // or only one of the updates will be applied, leading to incomplete data
        // expect(db.updatePerson).toHaveBeenCalledTimes(1)

        // The updatePerson call should have the correct properties
        expect(db.updatePerson).toHaveBeenCalledTimes(1)
        expect(db.updatePerson).toHaveBeenCalledWith(
            expect.objectContaining({
                id: sharedPerson.id,
                properties: {
                    initial_prop: 'initial_value',
                    prop_from_distinctId1: 'value1',
                    prop_from_distinctId2: 'value2',
                },
            }),
            expect.objectContaining({
                id: sharedPerson.id,
                properties: {
                    initial_prop: 'initial_value',
                    prop_from_distinctId1: 'value1',
                    prop_from_distinctId2: 'value2',
                },
            }),
            undefined,
            'updatePersonNoAssert'
        )
    })

    describe('moveDistinctIds', () => {
        it('should preserve cached merged properties when moving distinct IDs', async () => {
            const personStoreForBatch = getBatchStoreForBatch()

            // Create target person with some initial properties
            const targetPerson: InternalPerson = {
                ...person,
                id: 'target-id',
                properties: {
                    target_prop: 'target_value',
                    existing_target_prop: 'existing_target_value',
                },
                version: 5,
                is_identified: false,
            }

            const sourcePerson: InternalPerson = {
                ...person,
                id: 'source-id',
                properties: {
                    source_prop: 'source_value',
                },
                version: 4,
                is_identified: true,
            }

            // Step 1: Cache the target person (simulating fetchForUpdate)
            personStoreForBatch.setCachedPersonForUpdate(
                teamId,
                'target-distinct',
                fromInternalPerson(targetPerson, 'target-distinct')
            )

            // Step 2: Update target person with merged properties (simulating updatePersonForMerge)
            const mergeUpdate = {
                properties: {
                    source_prop: 'source_value',
                    rich_property: 'rich_value',
                    merged_from_source: 'merged_value',
                },
                is_identified: true,
            }
            await personStoreForBatch.updatePersonForMerge(targetPerson, mergeUpdate, 'target-distinct')

            // Verify the merge worked - check the final computed result
            const cacheAfterMerge = personStoreForBatch.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
            expect(cacheAfterMerge?.properties).toEqual({
                target_prop: 'target_value',
                existing_target_prop: 'existing_target_value',
            }) // Original properties from database
            expect(cacheAfterMerge?.properties_to_set).toEqual({
                source_prop: 'source_value',
                rich_property: 'rich_value',
                merged_from_source: 'merged_value',
                target_prop: 'target_value',
                existing_target_prop: 'existing_target_value',
            }) // Properties to set
            expect(cacheAfterMerge?.properties_to_unset).toEqual([]) // Properties to unset
            expect(cacheAfterMerge?.is_identified).toBe(true)

            // Step 3: moveDistinctIds - this should preserve the merged cache
            await personStoreForBatch.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct')

            // Step 4: Verify that cached merged properties are preserved
            const cacheAfterMove = personStoreForBatch.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
            expect(cacheAfterMove?.properties).toEqual({
                target_prop: 'target_value',
                existing_target_prop: 'existing_target_value',
            })
            expect(cacheAfterMove?.properties_to_set).toEqual({
                source_prop: 'source_value',
                rich_property: 'rich_value',
                merged_from_source: 'merged_value',
                target_prop: 'target_value',
                existing_target_prop: 'existing_target_value',
            })
            expect(cacheAfterMove?.properties_to_unset).toEqual([])
            expect(cacheAfterMove?.is_identified).toBe(true)
            expect(cacheAfterMove?.distinct_id).toBe('target-distinct')

            // Verify the source cache is cleared
            const sourceCacheAfterMove = personStoreForBatch.getCachedPersonForUpdateByPersonId(teamId, sourcePerson.id)
            expect(sourceCacheAfterMove).toBeUndefined()
        })

        it('should create fresh cache when no existing cache exists', async () => {
            const personStoreForBatch = getBatchStoreForBatch()

            const targetPerson: InternalPerson = {
                ...person,
                id: 'target-id',
                properties: {
                    target_prop: 'target_value',
                },
                version: 5,
            }

            const sourcePerson: InternalPerson = {
                ...person,
                id: 'source-id',
                properties: {
                    source_prop: 'source_value',
                },
                version: 4,
            }

            // No existing cache for target person
            expect(personStoreForBatch.getCachedPersonForUpdateByPersonId(teamId, targetPerson.id)).toBeUndefined()

            // Move distinct IDs
            await personStoreForBatch.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct')

            // Should create fresh cache from target person
            const cacheAfterMove = personStoreForBatch.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
            expect(cacheAfterMove?.properties).toEqual({
                target_prop: 'target_value',
            })
            expect(cacheAfterMove?.id).toBe(targetPerson.id)
            expect(cacheAfterMove?.distinct_id).toBe('target-distinct')
        })

        it('should clear source person cache', async () => {
            const personStoreForBatch = getBatchStoreForBatch()

            const targetPerson: InternalPerson = {
                ...person,
                id: 'target-id',
                properties: { target_prop: 'target_value' },
                version: 5,
            }

            const sourcePerson: InternalPerson = {
                ...person,
                id: 'source-id',
                properties: { source_prop: 'source_value' },
                version: 4,
            }

            // Set up cache for source person
            personStoreForBatch.setCachedPersonForUpdate(
                teamId,
                'source-distinct',
                fromInternalPerson(sourcePerson, 'source-distinct')
            )

            // Verify source cache exists
            expect(personStoreForBatch.getCachedPersonForUpdateByPersonId(teamId, sourcePerson.id)).toBeDefined()

            // Move distinct IDs
            await personStoreForBatch.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct')

            // Verify source cache is cleared
            expect(personStoreForBatch.getCachedPersonForUpdateByPersonId(teamId, sourcePerson.id)).toBeUndefined()
        })

        it('should handle complex merge scenario with multiple properties', async () => {
            const personStoreForBatch = getBatchStoreForBatch()

            const targetPerson: InternalPerson = {
                ...person,
                id: 'target-id',
                properties: {
                    target_prop: 'target_value',
                    shared_prop: 'original_value',
                    target_only: 'target_only_value',
                },
                version: 5,
                is_identified: false,
            }

            const sourcePerson: InternalPerson = {
                ...person,
                id: 'source-id',
                properties: {
                    source_prop: 'source_value',
                    shared_prop: 'updated_value',
                    source_only: 'source_only_value',
                },
                version: 4,
                is_identified: true,
            }

            // Step 1: Cache target person
            personStoreForBatch.setCachedPersonForUpdate(
                teamId,
                'target-distinct',
                fromInternalPerson(targetPerson, 'target-distinct')
            )

            // Step 2: Multiple merge operations
            await personStoreForBatch.updatePersonForMerge(
                targetPerson,
                {
                    properties: {
                        source_prop: 'source_value',
                        shared_prop: 'updated_value', // This should override
                    },
                    is_identified: true,
                },
                'target-distinct'
            )

            await personStoreForBatch.updatePersonForMerge(
                targetPerson,
                {
                    properties: {
                        additional_prop: 'additional_value',
                        source_only: 'source_only_value',
                    },
                },
                'target-distinct'
            )

            // Step 3: moveDistinctIds
            await personStoreForBatch.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct')

            // Step 4: Verify all merged properties are preserved
            const finalCache = personStoreForBatch.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
            expect(finalCache?.properties).toEqual({
                target_prop: 'target_value',
                shared_prop: 'original_value',
                target_only: 'target_only_value',
            })
            expect(finalCache?.is_identified).toBe(true)
            expect(finalCache?.properties_to_set).toEqual({
                source_prop: 'source_value',
                shared_prop: 'updated_value',
                additional_prop: 'additional_value',
                source_only: 'source_only_value',
                target_only: 'target_only_value',
                target_prop: 'target_value',
            })
            expect(finalCache?.properties_to_unset).toEqual([])
        })
    })
})
