import { DateTime } from 'luxon'

import { InternalPerson, TeamId } from '~/types'
import { DB } from '~/utils/db/db'
import { MessageSizeTooLarge } from '~/utils/db/error'

import { captureIngestionWarning } from '../utils'
import { BatchWritingPersonsStore } from './batch-writing-person-store'
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
        } as unknown as DB

        personStore = new BatchWritingPersonsStore(db)
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    it('should update person in cache', async () => {
        const personStoreForBatch = personStore.forBatch()
        const response = await personStoreForBatch.updatePersonForUpdate(
            person,
            { properties: { new_value: 'new_value' } },
            'test'
        )
        expect(response).toEqual([
            { ...person, version: 1, properties: { test: 'test', new_value: 'new_value' } },
            [],
            false,
        ])

        // Validate cache - should contain a PersonUpdate object
        const cache = (personStoreForBatch as any)['personUpdateCache']
        const cachedUpdate = cache.get('1:test')
        expect(cachedUpdate).toBeDefined()
        expect(cachedUpdate.distinct_id).toBe('test')
        expect(cachedUpdate.needs_write).toBe(true)
        expect(cachedUpdate.properties).toEqual({ test: 'test', new_value: 'new_value' })
        expect(cachedUpdate.team_id).toBe(1)
        expect(cachedUpdate.uuid).toBe('1')
    })

    it('should remove person from caches when deleted', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Add person to cache using the proper PersonUpdate structure
        let updateCache = (personStoreForBatch as any)['personUpdateCache']
        const personUpdate = fromInternalPerson(person, 'test')
        personUpdate.properties = { new_value: 'new_value' }
        personUpdate.needs_write = false
        updateCache.set('1:test', personUpdate)

        let checkCache = (personStoreForBatch as any)['personCheckCache']
        checkCache.set('1:test', person)

        const response = await personStoreForBatch.deletePerson(person, 'test')
        expect(response).toEqual([])

        // Validate cache
        updateCache = (personStoreForBatch as any)['personUpdateCache']
        checkCache = (personStoreForBatch as any)['personCheckCache']
        expect(updateCache.get('1:test')).toBeUndefined()
        expect(checkCache.get('1:test')).toBeUndefined()
    })

    it('should flush person updates with default NO_ASSERT mode', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Add a person update to cache
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

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
        db.updatePersonAssertVersion = jest.fn().mockResolvedValue(undefined)

        // Add a person update to cache
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        // Flush should retry optimistically then fallback to direct update
        await personStoreForBatch.flush()

        expect(db.updatePersonAssertVersion).toHaveBeenCalled()
        expect(db.fetchPerson).toHaveBeenCalled() // Called during conflict resolution
        expect(db.updatePerson).toHaveBeenCalled() // Fallback
    })

    it('should merge multiple updates for same person', async () => {
        const personStoreForBatch = personStore.forBatch()

        // First update
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { prop1: 'value1' } }, 'test')

        // Second update to same person
        await personStoreForBatch.updatePersonForUpdate(
            person,
            { properties: { test: 'value2', prop2: 'value2' } },
            'test'
        )

        // Check cache contains merged updates
        const cache = (personStoreForBatch as any)['personUpdateCache']
        const cachedUpdate = cache.get('1:test')
        expect(cachedUpdate.properties).toEqual({ test: 'value2', prop1: 'value1', prop2: 'value2' }) // Second update overwrites
        expect(cachedUpdate.needs_write).toBe(true)
    })

    describe('fetchForUpdate vs fetchForChecking', () => {
        it('should use separate caches for update and checking', async () => {
            const personStoreForBatch = personStore.forBatch()

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
            expect(personFromUpdate!.uuid).toBe(person.uuid)

            const updateCache = (personStoreForBatch as any)['personUpdateCache']
            const cachedPersonUpdate = updateCache.get('1:test-distinct2')
            expect(cachedPersonUpdate).toBeDefined()
            expect(cachedPersonUpdate.distinct_id).toBe('test-distinct2')
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
                return Promise.resolve(undefined) // version mismatch
            }
            return Promise.resolve(5) // success on 3rd try
        })

        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')
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
        db.updatePersonAssertVersion = jest.fn().mockResolvedValue(undefined)

        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')
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

        db.updatePersonAssertVersion = jest.fn().mockResolvedValue(undefined) // Always fail
        db.fetchPerson = jest.fn().mockResolvedValue(latestPerson)

        // Update with new properties
        await personStoreForBatch.updatePersonForUpdate(
            person,
            {
                properties: { new_prop: 'new_value', shared_prop: 'new_value' },
            },
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

        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        await expect(personStoreForBatch.flush()).rejects.toThrow('Database connection failed')
    })

    it('should handle partial failures in batch flush', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Set up multiple updates
        const person2 = { ...person, id: '2', uuid: '2' }
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { test: 'value1' } }, 'test1')
        await personStoreForBatch.updatePersonForUpdate(person2, { properties: { test: 'value2' } }, 'test2')

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
        const personStoreForBatch = personStore.forBatch()
        const person2 = { ...person, team_id: 2 }

        // Add to both caches for different teams
        const updateCache = (personStoreForBatch as any)['personUpdateCache']
        const checkCache = (personStoreForBatch as any)['personCheckCache']

        updateCache.set('1:test', fromInternalPerson(person, 'test'))
        updateCache.set('2:test', fromInternalPerson(person2, 'test'))
        checkCache.set('1:test', person)
        checkCache.set('2:test', person2)

        // Delete person from team 1
        await personStoreForBatch.deletePerson(person, 'test')

        // Only team 1 entries should be removed
        expect(updateCache.has('1:test')).toBe(false)
        expect(updateCache.has('2:test')).toBe(true)
        expect(checkCache.has('1:test')).toBe(false)
        expect(checkCache.has('2:test')).toBe(true)
    })

    it('should handle empty properties updates', async () => {
        const personStoreForBatch = personStore.forBatch()

        const result = await personStoreForBatch.updatePersonForUpdate(person, {}, 'test')
        expect(result[0]).toEqual(person) // Should return original person unchanged

        const cache = (personStoreForBatch as any)['personUpdateCache']
        const cachedUpdate = cache.get('1:test')
        expect(cachedUpdate.needs_write).toBe(true) // Still marked for write
    })

    it('should handle null and undefined property values', async () => {
        const personStoreForBatch = personStore.forBatch()

        await personStoreForBatch.updatePersonForUpdate(
            person,
            { properties: { null_prop: null, undefined_prop: undefined } },
            'test'
        )

        const cache = (personStoreForBatch as any)['personUpdateCache']
        const cachedUpdate = cache.get('1:test')
        expect(cachedUpdate.properties.null_prop).toBeNull()
        expect(cachedUpdate.properties.undefined_prop).toBeUndefined()

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
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        // Flush should handle the error and capture warning
        await personStoreForBatch.flush()

        expect(db.updatePerson).toHaveBeenCalled()
        expect(captureIngestionWarning).toHaveBeenCalledWith(
            db.kafkaProducer,
            teamId,
            'person_upsert_message_size_too_large',
            {
                personUuid: person.uuid,
                distinctId: 'test',
            }
        )
    })

    describe('dbWriteMode functionality', () => {
        describe('flush with NO_ASSERT mode', () => {
            it('should call updatePersonNoAssert directly without retries', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'NO_ASSERT' })
                const personStoreForBatch = personStore.forBatch()

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
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

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
                    'test'
                )

                await expect(personStoreForBatch.flush()).rejects.toThrow('Database error')
                expect(db.updatePerson).toHaveBeenCalledTimes(2) // 1 for update, 1 for fallback
                expect(db.updatePersonAssertVersion).not.toHaveBeenCalled()
            })
        })

        describe('flush with ASSERT_VERSION mode', () => {
            it('should call updatePersonAssertVersion with retries', async () => {
                const personStore = new BatchWritingPersonsStore(db, { dbWriteMode: 'ASSERT_VERSION' })
                const personStoreForBatch = personStore.forBatch()

                db.updatePersonAssertVersion = jest.fn().mockResolvedValue(5) // success

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
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
                db.updatePersonAssertVersion = jest.fn().mockResolvedValue(undefined)

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
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

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
                    'test'
                )
                await personStoreForBatch.flush()

                expect(db.updatePersonAssertVersion).toHaveBeenCalled()
                expect(captureIngestionWarning).toHaveBeenCalledWith(
                    db.kafkaProducer,
                    teamId,
                    'person_upsert_message_size_too_large',
                    {
                        personUuid: person.uuid,
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

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
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

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
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

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
                    'test'
                )
                await personStoreForBatch.flush()

                expect(captureIngestionWarning).toHaveBeenCalledWith(
                    db.kafkaProducer,
                    teamId,
                    'person_upsert_message_size_too_large',
                    {
                        personUuid: person.uuid,
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

                await personStoreForBatch.updatePersonForUpdate(
                    person,
                    { properties: { new_value: 'new_value' } },
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
                db.updatePersonAssertVersion = jest.fn().mockResolvedValue(5)

                await Promise.all([
                    noAssertBatch.updatePersonForUpdate(person, { properties: { mode: 'no_assert' } }, 'test1'),
                    assertVersionBatch.updatePersonForUpdate(
                        person2,
                        { properties: { mode: 'assert_version' } },
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
            .mockResolvedValueOnce(undefined) // First call fails (version mismatch)
            .mockResolvedValueOnce(3) // Second call succeeds with new version

        // Mock fetchPerson to return the updated person when called during conflict resolution
        db.fetchPerson = jest.fn().mockResolvedValue(updatedByOtherPod)

        // Process an event that will override one of the properties
        // We pass the initial person directly, so no initial fetch is needed
        await personStoreForBatch.updatePersonForUpdate(
            initialPerson,
            { properties: { existing_prop2: 'updated_by_this_pod' } },
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
                property_changeset: {
                    existing_prop2: 'updated_by_this_pod', // Only the changed property should be in changeset
                },
            })
        )
    })
})
