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
    personFetchForCheckingCacheOperationsCounter: { inc: jest.fn() },
    personFetchForUpdateCacheOperationsCounter: { inc: jest.fn() },
    personMethodCallsPerBatchHistogram: { observe: jest.fn() },
    personOptimisticUpdateConflictsPerBatchCounter: { inc: jest.fn() },
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
            updatePersonDeprecated: jest.fn().mockImplementation(() => {
                dbCounter++
                const personCopy = { ...person, version: dbCounter }
                return Promise.resolve([personCopy, []])
            }),
            updatePersonOptimistically: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter) // Return new version number
            }),
            deletePerson: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
        } as unknown as DB

        personStore = new BatchWritingPersonsStore(db, {
            optimisticUpdatesEnabled: true,
        })
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
        expect(response).toEqual([{ ...person, version: 1, properties: { test: 'test', new_value: 'new_value' } }, []])

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

    it('should flush person updates optimistically', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Add a person update to cache
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        // Flush should call updatePersonOptimistically
        await personStoreForBatch.flush()

        expect(db.updatePersonOptimistically).toHaveBeenCalledTimes(1)
        expect(db.updatePersonDeprecated).not.toHaveBeenCalled()
    })

    it('should fallback to direct update when optimistic update fails', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Mock optimistic update to fail
        db.updatePersonOptimistically = jest.fn().mockResolvedValue(undefined) // version mismatch

        // Add a person update to cache
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        // Flush should retry optimistically then fallback to direct update
        await personStoreForBatch.flush()

        expect(db.updatePersonOptimistically).toHaveBeenCalled()
        expect(db.fetchPerson).toHaveBeenCalled() // Called during conflict resolution
        expect(db.updatePersonDeprecated).toHaveBeenCalled() // Fallback
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
        const personStoreForBatch = personStore.forBatch()
        let callCount = 0

        // Mock to fail first few times, then succeed
        db.updatePersonOptimistically = jest.fn().mockImplementation(() => {
            callCount++
            if (callCount < 3) {
                return Promise.resolve(undefined) // version mismatch
            }
            return Promise.resolve(5) // success on 3rd try
        })

        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')
        await personStoreForBatch.flush()

        expect(db.updatePersonOptimistically).toHaveBeenCalledTimes(3)
        expect(db.fetchPerson).toHaveBeenCalledTimes(2) // Called for each conflict
        expect(db.updatePersonDeprecated).not.toHaveBeenCalled() // Shouldn't fallback if retries succeed
    })

    it('should fallback to direct update after max retries', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Mock to always fail optimistic updates
        db.updatePersonOptimistically = jest.fn().mockResolvedValue(undefined)

        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')
        await personStoreForBatch.flush()

        // Should try optimistic update multiple times based on config
        expect(db.updatePersonOptimistically).toHaveBeenCalledTimes(5) // default max retries
        expect(db.updatePersonDeprecated).toHaveBeenCalledTimes(1) // fallback
    })

    it('should merge properties during conflict resolution', async () => {
        const personStoreForBatch = personStore.forBatch()
        const latestPerson = {
            ...person,
            version: 3,
            properties: { existing_prop: 'existing_value', shared_prop: 'old_value' },
        }

        db.updatePersonOptimistically = jest.fn().mockResolvedValue(undefined) // Always fail
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
        expect(db.updatePersonDeprecated).toHaveBeenCalledWith(
            expect.objectContaining({
                properties: {
                    existing_prop: 'existing_value',
                    shared_prop: 'old_value',
                },
                version: 3, // Should use latest version
            }),
            expect.objectContaining({
                properties: {
                    existing_prop: 'existing_value',
                    new_prop: 'new_value',
                    shared_prop: 'new_value',
                    test: 'test',
                },
                version: 3,
            }),
            expect.anything(),
            'forUpdate'
        )
    })

    it('should handle database errors gracefully during flush', async () => {
        const personStoreForBatch = personStore.forBatch()

        db.updatePersonOptimistically = jest.fn().mockRejectedValue(new Error('Database connection failed'))
        db.updatePersonDeprecated = jest.fn().mockRejectedValue(new Error('Database connection failed'))

        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        await expect(personStoreForBatch.flush()).rejects.toThrow('Database connection failed')
    })

    it('should handle partial failures in batch flush', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Set up multiple updates
        const person2 = { ...person, id: '2', uuid: '2' }
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { test: 'value1' } }, 'test1')
        await personStoreForBatch.updatePersonForUpdate(person2, { properties: { test: 'value2' } }, 'test2')

        // Mock first update to succeed, second to fail (both optimistic and fallback)
        let optimisticCallCount = 0
        let fallbackCallCount = 0

        db.updatePersonOptimistically = jest.fn().mockImplementation(() => {
            optimisticCallCount++
            if (optimisticCallCount === 1) {
                return Promise.resolve(5) // success for first person
            }
            return Promise.resolve(undefined) // version mismatch for second person, triggering fallback
        })

        db.updatePersonDeprecated = jest.fn().mockImplementation(() => {
            fallbackCallCount++
            if (fallbackCallCount === 1) {
                throw new Error('Database error') // Fallback fails for second person
            }
            return Promise.resolve([person2, []])
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

        expect(db.updatePersonOptimistically).toHaveBeenCalledWith(
            expect.objectContaining({
                properties: { null_prop: null, undefined_prop: undefined, test: 'test' },
            })
        )
    })

    it('should handle MessageSizeTooLarge errors and capture warning', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Mock optimistic update to fail with MessageSizeTooLarge
        db.updatePersonOptimistically = jest.fn().mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

        // Add a person update to cache
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        // Flush should handle the error and capture warning
        await personStoreForBatch.flush()

        expect(db.updatePersonOptimistically).toHaveBeenCalled()
        expect(db.updatePersonDeprecated).not.toHaveBeenCalled() // Should not fallback to direct update
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

    it('should use transaction with FOR UPDATE when falling back from optimistic update', async () => {
        const personStoreForBatch = personStore.forBatch()

        // Mock optimistic update to fail
        db.updatePersonOptimistically = jest.fn().mockResolvedValue(undefined) // version mismatch

        // Add a person update to cache
        await personStoreForBatch.updatePersonForUpdate(person, { properties: { new_value: 'new_value' } }, 'test')

        // Flush should retry optimistically then fallback to transactional update
        await personStoreForBatch.flush()

        // Assert fetchPerson was called with forUpdate: true
        expect(db.fetchPerson).toHaveBeenCalledWith(person.team_id, 'test', { forUpdate: true })

        // Assert updatePersonDeprecated was called with a transaction object
        expect(db.updatePersonDeprecated).toHaveBeenCalledWith(
            expect.any(Object),
            expect.any(Object),
            expect.anything(), // tx
            'forUpdate'
        )
    })
})
