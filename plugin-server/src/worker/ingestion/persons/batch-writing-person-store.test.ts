import { DateTime } from 'luxon'

import { KafkaProducerWrapper } from '~/kafka/producer'
import { InternalPerson, TeamId } from '~/types'
import { MessageSizeTooLarge } from '~/utils/db/error'
import { PostgresRouter } from '~/utils/db/postgres'

import { captureIngestionWarning } from '../utils'
import { BatchWritingPersonsStore } from './batch-writing-person-store'
import {
    personProfileBatchIgnoredPropertiesCounter,
    personProfileBatchUpdateOutcomeCounter,
    personPropertyKeyUpdateCounter,
} from './metrics'
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
    personProfileBatchIgnoredPropertiesCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personProfileBatchUpdateOutcomeCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personPropertyKeyUpdateCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personRetryAttemptsHistogram: { observe: jest.fn() },
    personWriteMethodAttemptCounter: { inc: jest.fn() },
    personWriteMethodLatencyHistogram: { observe: jest.fn() },
    totalPersonUpdateLatencyPerBatchHistogram: { observe: jest.fn() },
}))

describe('BatchWritingPersonStore', () => {
    // let db: DB
    let mockKafkaProducer: KafkaProducerWrapper
    let mockPostgres: PostgresRouter
    let personStore: BatchWritingPersonsStore
    let mockRepo: any
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

        mockPostgres = {
            transaction: jest.fn().mockImplementation(async (_usage, _tag, transaction) => {
                return await transaction(transaction)
            }),
        } as unknown as PostgresRouter

        mockKafkaProducer = {
            queueMessages: jest.fn(),
        } as unknown as KafkaProducerWrapper

        mockRepo = createMockRepository()
        personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    const getPersonsStore = () => personStore

    const createMockRepository = () => {
        const mockRepo = {
            fetchPerson: jest.fn().mockResolvedValue(person),
            fetchPersonDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            createPerson: jest.fn().mockResolvedValue([person, []]),
            updatePerson: jest.fn().mockResolvedValue([person, [], false]),
            updatePersonAssertVersion: jest.fn().mockResolvedValue([person.version + 1, []]),
            updatePersonsBatch: jest.fn().mockImplementation((updates) => {
                // Return a map with success for each update
                const results = new Map()
                for (const update of updates) {
                    results.set(update.uuid, {
                        success: true,
                        version: update.version + 1,
                        kafkaMessage: { topic: 'test', messages: [] },
                    })
                }
                return Promise.resolve(results)
            }),
            deletePerson: jest.fn().mockResolvedValue([]),
            addDistinctId: jest.fn().mockResolvedValue([]),
            moveDistinctIds: jest.fn().mockResolvedValue({ success: true, messages: [], distinctIdsMoved: [] }),
            addPersonlessDistinctId: jest.fn().mockResolvedValue(true),
            addPersonlessDistinctIdForMerge: jest.fn().mockResolvedValue(true),
            addPersonlessDistinctIdsBatch: jest.fn().mockResolvedValue(new Map()),
            personPropertiesSize: jest.fn().mockResolvedValue(1024),
            updateCohortsAndFeatureFlagsForMerge: jest.fn().mockResolvedValue(undefined),
            inTransaction: jest.fn().mockImplementation(async (description, transaction) => {
                return await transaction(transaction)
            }),
        }
        return mockRepo
    }

    const createMockTransaction = () => {
        const mockTransaction = {
            fetchPersonDistinctIds: jest.fn().mockResolvedValue([]),
            createPerson: jest.fn().mockResolvedValue([person, []]),
            updatePerson: jest.fn().mockResolvedValue([person, [], false]),
            deletePerson: jest.fn().mockResolvedValue([]),
            addDistinctId: jest.fn().mockResolvedValue([]),
            moveDistinctIds: jest.fn().mockResolvedValue({ success: true, messages: [], distinctIdsMoved: [] }),
            addPersonlessDistinctIdForMerge: jest.fn().mockResolvedValue(true),
            updateCohortsAndFeatureFlagsForMerge: jest.fn().mockResolvedValue(undefined),
        }
        return mockTransaction
    }

    it('should update person in cache', async () => {
        const personStore = getPersonsStore()
        const response = await personStore.updatePersonWithPropertiesDiffForUpdate(
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
        const cache = (personStore as any)['personUpdateCache']
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
        const personStore = getPersonsStore()
        const response = await personStore.updatePersonWithPropertiesDiffForUpdate(
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

        const response2 = await personStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            {},
            ['value_to_unset'],
            {},
            'test'
        )
        expect(response2).toEqual([{ ...person, version: 1, properties: { test: 'test' } }, [], false])

        // Check cache contains merged updates with conflict resolution
        // When unsetting a property that was previously set, it should be removed from properties_to_set
        const cache = personStore.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties).toEqual({ test: 'test' })
        expect(cachedUpdate.properties_to_set).toEqual({ test: 'test' })
        expect(cachedUpdate.properties_to_unset).toEqual(['value_to_unset'])
        expect(cachedUpdate.needs_write).toBe(true)

        await personStore.flush()

        // In NO_ASSERT mode, we use batch updates
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    uuid: person.uuid,
                    properties_to_unset: ['value_to_unset'],
                }),
            ])
        )
    })

    it('should handle setting a property after unsetting it (re-setting)', async () => {
        const personStore = getPersonsStore()

        // First, unset a property
        await personStore.updatePersonWithPropertiesDiffForUpdate(person, {}, ['prop_to_toggle'], {}, 'test')

        // Then, set the same property again
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            { prop_to_toggle: 'new_value' },
            [],
            {},
            'test'
        )

        // Check cache - property should be in properties_to_set and NOT in properties_to_unset
        const cache = personStore.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties_to_set).toEqual({ test: 'test', prop_to_toggle: 'new_value' })
        expect(cachedUpdate.properties_to_unset).toEqual([])

        await personStore.flush()

        // In NO_ASSERT mode, we use batch updates
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    uuid: person.uuid,
                    properties_to_set: { test: 'test', prop_to_toggle: 'new_value' },
                    properties_to_unset: [],
                }),
            ])
        )
    })

    it('should handle unsetting a property after setting it', async () => {
        const personStore = getPersonsStore()

        // First, set a property
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            { prop_to_toggle: 'some_value' },
            [],
            {},
            'test'
        )

        // Then, unset the same property
        await personStore.updatePersonWithPropertiesDiffForUpdate(person, {}, ['prop_to_toggle'], {}, 'test')

        // Check cache - property should be in properties_to_unset and NOT in properties_to_set
        const cache = personStore.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties_to_set).toEqual({ test: 'test' })
        expect(cachedUpdate.properties_to_unset).toEqual(['prop_to_toggle'])

        await personStore.flush()

        // In NO_ASSERT mode, we use batch updates
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    uuid: person.uuid,
                    properties_to_unset: ['prop_to_toggle'],
                }),
            ])
        )
    })

    it('should remove person from caches when deleted', async () => {
        const mockRepo = createMockRepository()
        const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

        // Add person to cache using the proper PersonUpdate structure
        let updateCache = personStore.getUpdateCache()
        const personUpdate = fromInternalPerson(person, 'test')
        personUpdate.properties = { new_value: 'new_value' }
        personUpdate.needs_write = false
        updateCache.set(`${teamId}:${person.id}`, personUpdate)

        let checkCache = personStore.getCheckCache()
        checkCache.set(`${teamId}:test`, person)

        personStore.setDistinctIdToPersonId(teamId, 'test', person.id)

        const response = await personStore.deletePerson(person, 'test')
        expect(response).toEqual([])
        // The cached person update should be passed to deletePerson
        expect(mockRepo.deletePerson).toHaveBeenCalledWith(
            expect.objectContaining({
                ...person,
                properties: { new_value: 'new_value' },
            })
        )

        // Validate cache
        updateCache = personStore.getUpdateCache()
        checkCache = personStore.getCheckCache()
        expect(updateCache.get(`${teamId}:${person.id}`)).toBeUndefined()
        expect(checkCache.get(`${teamId}:${person.id}`)).toBeUndefined()
    })

    it('should flush person updates with default NO_ASSERT mode', async () => {
        // Add a person update to cache
        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { new_value: 'new_value' }, [], {}, 'test')

        // Flush should call updatePersonsBatch (NO_ASSERT default mode uses batch updates)
        await personStore.flush()

        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()
    })

    it('should fallback to direct update when optimistic update fails', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
            dbWriteMode: 'ASSERT_VERSION',
        })
        const personStore = assertVersionStore

        // Mock optimistic update to fail (version mismatch)
        mockRepo.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []])

        // Add a person update to cache
        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { new_value: 'new_value' }, [], {}, 'test')

        // Flush should retry optimistically then fallback to direct update
        await personStore.flush()

        expect(mockRepo.updatePersonAssertVersion).toHaveBeenCalled()
        expect(mockRepo.fetchPerson).toHaveBeenCalled() // Called during conflict resolution
        expect(mockRepo.updatePerson).toHaveBeenCalled() // Fallback
    })

    it('should merge multiple updates for same person', async () => {
        const personStore = getPersonsStore()

        // First update
        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { prop1: 'value1' }, [], {}, 'test')

        // Second update to same person
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            { test: 'value2', prop2: 'value2' },
            [],
            {},
            'test'
        )

        // Check cache contains merged updates
        const cache = personStore.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties).toEqual({ test: 'test' }) // Original properties from database
        expect(cachedUpdate.properties_to_set).toEqual({ prop1: 'value1', test: 'value2', prop2: 'value2' }) // Merged properties to set
        expect(cachedUpdate.properties_to_unset).toEqual([]) // No properties to unset
        expect(cachedUpdate.needs_write).toBe(true)
    })

    describe('fetchForUpdate vs fetchForChecking', () => {
        it('should use separate caches for update and checking', async () => {
            const personStore = getPersonsStore()

            // Fetch for checking should cache in check cache
            const personFromCheck = await personStore.fetchForChecking(teamId, 'test-distinct')
            expect(personFromCheck).toEqual(person)

            const checkCache = (personStore as any)['personCheckCache']
            expect(checkCache.get('1:test-distinct')).toEqual(person)

            // Fetch for update should cache in update cache and return PersonUpdate converted to InternalPerson
            const personFromUpdate = await personStore.fetchForUpdate(teamId, 'test-distinct2')
            expect(personFromUpdate).toBeDefined()
            expect(personFromUpdate!.id).toBe(person.id)
            expect(personFromUpdate!.team_id).toBe(person.team_id)
            expect(personFromUpdate!.id).toBe(person.id)

            const updateCache = personStore.getUpdateCache()
            const cachedPersonUpdate = updateCache.get(`${teamId}:${person.id}`)
            expect(cachedPersonUpdate).toBeDefined()
            expect(cachedPersonUpdate!.distinct_id).toBe('test-distinct2')
        })

        it('should handle cache hits for both checking and updating', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // First fetch should hit the database
            await personStore.fetchForChecking(teamId, 'test-distinct')
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1)

            // Second fetch should hit the cache
            await personStore.fetchForChecking(teamId, 'test-distinct')
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1) // No additional call

            // Similar for update cache
            await personStore.fetchForUpdate(teamId, 'test-distinct2')
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(2)

            await personStore.fetchForUpdate(teamId, 'test-distinct2')
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(2) // No additional call
        })

        it('should prefer update cache over check cache in fetchForChecking', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // First populate update cache
            await personStore.fetchForUpdate(teamId, 'test-distinct')

            // Reset the mock to track new calls
            jest.clearAllMocks()

            // fetchForChecking should use the cached PersonUpdate instead of hitting DB
            const result = await personStore.fetchForChecking(teamId, 'test-distinct')
            expect(result).toBeDefined()
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
        })

        it('should handle null results from database', async () => {
            const mockRepo = createMockRepository()
            mockRepo.fetchPerson = jest.fn().mockResolvedValue(undefined)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const checkResult = await personStore.fetchForChecking(teamId, 'nonexistent')
            expect(checkResult).toBeNull()

            const updateResult = await personStore.fetchForUpdate(teamId, 'nonexistent')
            expect(updateResult).toBeNull()
        })
    })

    it('should retry optimistic updates with exponential backoff', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const testMockRepo = createMockRepository()
        const assertVersionStore = new BatchWritingPersonsStore(testMockRepo, mockKafkaProducer, {
            dbWriteMode: 'ASSERT_VERSION',
        })
        const personStore = assertVersionStore
        let callCount = 0

        // Mock to fail first few times, then succeed
        testMockRepo.updatePersonAssertVersion = jest.fn().mockImplementation(() => {
            callCount++
            if (callCount < 3) {
                return Promise.resolve([undefined, []]) // version mismatch
            }
            return Promise.resolve([5, []]) // success on 3rd try
        })

        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { new_value: 'new_value' }, [], {}, 'test')
        await personStore.flush()

        expect(testMockRepo.updatePersonAssertVersion).toHaveBeenCalledTimes(3)
        expect(testMockRepo.fetchPerson).toHaveBeenCalledTimes(2) // Called for each conflict
        expect(testMockRepo.updatePerson).not.toHaveBeenCalled() // Shouldn't fallback if retries succeed
    })

    it('should fallback to direct update after max retries', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
            dbWriteMode: 'ASSERT_VERSION',
        })
        const personStore = assertVersionStore

        // Mock to always fail optimistic updates
        mockRepo.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []])

        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { new_value: 'new_value' }, [], {}, 'test')
        await personStore.flush()

        // Should try optimistic update multiple times based on config (1 initial + 5 retries = 6 total)
        expect(mockRepo.updatePersonAssertVersion).toHaveBeenCalledTimes(6) // default max retries
        expect(mockRepo.updatePerson).toHaveBeenCalledTimes(1) // fallback
    })

    it('should merge properties during conflict resolution', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
            dbWriteMode: 'ASSERT_VERSION',
        })
        const personStore = assertVersionStore
        const latestPerson = {
            ...person,
            version: 3,
            properties: { existing_prop: 'existing_value', shared_prop: 'old_value' },
        }

        mockRepo.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []]) // Always fail, but we don't care about the version
        mockRepo.fetchPerson = jest.fn().mockResolvedValue(latestPerson)

        // Update with new properties
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            { new_prop: 'new_value', shared_prop: 'new_value' },
            [],
            {},
            'test'
        )

        await personStore.flush()

        // Verify the direct update was called with merged properties
        expect(mockRepo.updatePerson).toHaveBeenCalledWith(
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
            'updatePersonNoAssert'
        )
    })

    it('should handle database errors gracefully during flush', async () => {
        // Mock batch update to throw an error - all persons will fail
        mockRepo.updatePersonsBatch = jest.fn().mockImplementation(() => {
            throw new Error('Database connection failed')
        })

        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { new_value: 'new_value' }, [], {}, 'test')

        await expect(personStore.flush()).rejects.toThrow('Database connection failed')
    })

    it('should handle partial failures in batch flush', async () => {
        // Set up multiple updates
        const person2 = { ...person, id: '2', uuid: '2' }
        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { test: 'value1' }, [], {}, 'test1')
        await personStore.updatePersonWithPropertiesDiffForUpdate(person2, { test: 'value2' }, [], {}, 'test2')

        // Mock batch update to fail for person2 (returns error in results map)
        mockRepo.updatePersonsBatch = jest.fn().mockImplementation((updates) => {
            const results = new Map()
            for (const update of updates) {
                if (update.uuid === person.uuid) {
                    results.set(update.uuid, {
                        success: true,
                        version: update.version + 1,
                        kafkaMessage: { topic: 'test', messages: [] },
                    })
                } else {
                    results.set(update.uuid, {
                        success: false,
                        error: new Error('Database error'),
                    })
                }
            }
            return Promise.resolve(results)
        })

        // Mock fallback to also fail
        mockRepo.updatePerson = jest.fn().mockRejectedValue(new Error('Database error'))

        await expect(personStore.flush()).rejects.toThrow('Database error')
    })

    it('should handle clearing cache for different team IDs', async () => {
        const mockRepo = createMockRepository()
        const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)
        const person2 = { ...person, id: 'person2-id', uuid: 'person2-uuid', team_id: 2 }

        // Add to both caches for different teams
        const updateCache = personStore.getUpdateCache()
        const checkCache = personStore.getCheckCache()

        updateCache.set(`${person.team_id}:${person.id}`, fromInternalPerson(person, 'test'))
        updateCache.set(`${person2.team_id}:${person2.id}`, fromInternalPerson(person2, 'test'))
        checkCache.set(`${person.team_id}:test`, person)
        checkCache.set(`${person2.team_id}:test`, person2)
        personStore.setDistinctIdToPersonId(person.team_id, 'test', person.id)
        personStore.setDistinctIdToPersonId(person2.team_id, 'test', person2.id)

        // Delete person from team 1
        await personStore.deletePerson(person, 'test')
        expect(mockRepo.deletePerson).toHaveBeenCalledWith(
            expect.objectContaining({
                ...person,
                properties: { test: 'test' },
            })
        )

        // Only team 1 entries should be removed
        expect(updateCache.has(`${person.team_id}:${person.id}`)).toBe(false)
        expect(updateCache.has(`${person2.team_id}:${person2.id}`)).toBe(true)
        expect(checkCache.has(`${person.team_id}:test`)).toBe(false)
        expect(checkCache.has(`${person2.team_id}:test`)).toBe(true)
    })

    it('should handle empty properties updates', async () => {
        const personStore = getPersonsStore()

        const result = await personStore.updatePersonWithPropertiesDiffForUpdate(person, {}, [], {}, 'test')
        expect(result[0]).toEqual(person) // Should return original person unchanged

        const cache = personStore.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.needs_write).toBe(true) // Still marked for write
    })

    it('should handle null and undefined property values', async () => {
        const personStore = getPersonsStore()

        await personStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            { null_prop: null, undefined_prop: undefined },
            [],
            {},
            'test'
        )

        const cache = personStore.getUpdateCache()
        const cachedUpdate = cache.get(`${teamId}:${person.id}`)!
        expect(cachedUpdate.properties_to_set.null_prop).toBeNull()
        expect(cachedUpdate.properties_to_set.undefined_prop).toBeUndefined()

        await personStore.flush()

        // In NO_ASSERT mode, we use batch updates
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    uuid: person.uuid,
                    properties_to_set: expect.objectContaining({
                        null_prop: null,
                        undefined_prop: undefined,
                    }),
                }),
            ])
        )
    })

    it('should handle MessageSizeTooLarge errors and capture warning', async () => {
        // Mock batch update to fail for this person, then fallback to fail with MessageSizeTooLarge
        mockRepo.updatePersonsBatch = jest.fn().mockImplementation((updates) => {
            const results = new Map()
            for (const update of updates) {
                results.set(update.uuid, {
                    success: false,
                    error: new Error('batch failed'),
                })
            }
            return Promise.resolve(results)
        })
        mockRepo.updatePerson = jest.fn().mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

        // Add a person update to cache
        await personStore.updatePersonWithPropertiesDiffForUpdate(person, { new_value: 'new_value' }, [], {}, 'test')

        // Flush should handle the error and capture warning
        await personStore.flush()

        expect(mockRepo.updatePersonsBatch).toHaveBeenCalled()
        expect(captureIngestionWarning).toHaveBeenCalledWith(
            mockKafkaProducer,
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
            it('should call updatePersonsBatch directly without retries', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
                    dbWriteMode: 'NO_ASSERT',
                })

                await personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStore.flush()

                // NO_ASSERT mode uses batch updates
                expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
                expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()
                expect(mockPostgres.transaction).not.toHaveBeenCalled()
            })

            it('should fallback with NO_ASSERT mode when batch fails', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
                    dbWriteMode: 'NO_ASSERT',
                    maxOptimisticUpdateRetries: 5,
                })

                // Mock batch update to fail
                mockRepo.updatePersonsBatch = jest.fn().mockImplementation((updates) => {
                    const results = new Map()
                    for (const update of updates) {
                        results.set(update.uuid, {
                            success: false,
                            error: new Error('Batch failed'),
                        })
                    }
                    return Promise.resolve(results)
                })
                // Mock fallback to also fail
                mockRepo.updatePerson = jest.fn().mockRejectedValue(new Error('Database error'))

                await personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )

                await expect(personStore.flush()).rejects.toThrow('Database error')
                expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
                expect(mockRepo.updatePerson).toHaveBeenCalled() // Fallback was attempted
                expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()
            })
        })

        describe('flush with ASSERT_VERSION mode', () => {
            it('should call updatePersonAssertVersion with retries', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
                    dbWriteMode: 'ASSERT_VERSION',
                })

                mockRepo.updatePersonAssertVersion = jest.fn().mockResolvedValue([5, []]) // success

                await personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStore.flush()

                expect(mockRepo.updatePersonAssertVersion).toHaveBeenCalledTimes(1)
                expect(mockRepo.updatePerson).not.toHaveBeenCalled()
                expect(mockPostgres.transaction).not.toHaveBeenCalled()
            })

            it('should retry on version conflicts and eventually fallback', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
                    dbWriteMode: 'ASSERT_VERSION',
                    maxOptimisticUpdateRetries: 2,
                })

                // Mock to always fail optimistic updates
                mockRepo.updatePersonAssertVersion = jest.fn().mockResolvedValue([undefined, []])

                await personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStore.flush()

                expect(mockRepo.updatePersonAssertVersion).toHaveBeenCalledTimes(3) // 1 initial + 2 retries
                expect(mockRepo.updatePerson).toHaveBeenCalledTimes(1) // fallback
            })

            it('should handle MessageSizeTooLarge in ASSERT_VERSION mode', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
                    dbWriteMode: 'ASSERT_VERSION',
                })

                mockRepo.updatePersonAssertVersion = jest
                    .fn()
                    .mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

                await personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStore.flush()

                expect(mockRepo.updatePersonAssertVersion).toHaveBeenCalled()
                expect(captureIngestionWarning).toHaveBeenCalledWith(
                    mockKafkaProducer,
                    teamId,
                    'person_upsert_message_size_too_large',
                    {
                        personId: person.id,
                        distinctId: 'test',
                    }
                )
                expect(mockRepo.updatePerson).not.toHaveBeenCalled() // No fallback for MessageSizeTooLarge
            })
        })

        describe('concurrent updates with different dbWriteModes', () => {
            it('should handle multiple updates with different modes correctly', async () => {
                const noAssertMockRepo = createMockRepository()
                const assertVersionMockRepo = createMockRepository()

                const noAssertStore = new BatchWritingPersonsStore(noAssertMockRepo, mockKafkaProducer, {
                    dbWriteMode: 'NO_ASSERT',
                })
                const assertVersionStore = new BatchWritingPersonsStore(assertVersionMockRepo, mockKafkaProducer, {
                    dbWriteMode: 'ASSERT_VERSION',
                })

                const noAssertBatch = noAssertStore
                const assertVersionBatch = assertVersionStore

                const person2 = { ...person, id: '2', uuid: '2' }

                // Mock successful updates
                assertVersionMockRepo.updatePersonAssertVersion = jest.fn().mockResolvedValue([5, []])

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

                expect(noAssertMockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1) // NO_ASSERT mode uses batch
                expect(assertVersionMockRepo.updatePersonAssertVersion).toHaveBeenCalledTimes(1) // ASSERT_VERSION mode
            })
        })
    })

    it('should handle concurrent updates with ASSERT_VERSION mode and preserve both properties', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const mockRepo = createMockRepository()
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer, {
            dbWriteMode: 'ASSERT_VERSION',
        })
        const personStore = assertVersionStore

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
        mockRepo.updatePersonAssertVersion = jest
            .fn()
            .mockResolvedValueOnce([undefined, []]) // First call fails (version mismatch)
            .mockResolvedValueOnce([3, []]) // Second call succeeds with new version

        // Mock fetchPerson to return the updated person when called during conflict resolution
        mockRepo.fetchPerson = jest.fn().mockResolvedValue(updatedByOtherPod)

        // Process an event that will override one of the properties
        // We pass the initial person directly, so no initial fetch is needed
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            initialPerson,
            { existing_prop2: 'updated_by_this_pod' },
            [],
            {},
            'test'
        )

        // Flush should trigger optimistic update, fail, then merge and retry
        await personStore.flush()

        // Verify the optimistic update was attempted (should be called twice: once initially, once on retry)
        expect(mockRepo.updatePersonAssertVersion).toHaveBeenCalledTimes(2)

        // Verify fetchPerson was called once during conflict resolution
        expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1)

        // Since the second retry succeeds, there should be no fallback to updatePerson
        expect(mockRepo.updatePerson).not.toHaveBeenCalled()

        // Verify the second call to updatePersonAssertVersion had the merged properties
        expect(mockRepo.updatePersonAssertVersion).toHaveBeenLastCalledWith(
            expect.objectContaining({
                version: 2, // Should use the latest version from the database (updatedByOtherPod has version 2)
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
        const mockRepo = createMockRepository()
        mockRepo.fetchPerson = jest.fn().mockImplementation(() => {
            return Promise.resolve(sharedPerson)
        })
        const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

        // Update via first distinct ID
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            { prop_from_distinctId1: 'value1' },
            [],
            {},
            distinctId1
        )

        // Update via second distinct ID
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            { prop_from_distinctId2: 'value2' },
            [],
            {},
            distinctId2
        )

        const cache = personStore.getUpdateCache()

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

        // Flush should consolidate these into a single DB update (via batch)
        await personStore.flush()

        // In NO_ASSERT mode, we use batch updates
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    id: sharedPerson.id,
                    properties_to_set: {
                        initial_prop: 'initial_value',
                        prop_from_distinctId1: 'value1',
                        prop_from_distinctId2: 'value2',
                    },
                }),
            ])
        )
    })

    it('should handle set/unset conflicts when merging updates for same person via different distinct IDs', async () => {
        // This test validates that when two distinct IDs point to the same person,
        // and one unsets a property while the other sets it, the conflict is resolved correctly
        const distinctId1 = 'user-email@example.com'
        const distinctId2 = 'user-device-abc123'

        const sharedPerson = {
            ...person,
            properties: {
                existing_prop: 'existing_value',
            },
        }

        const mockRepo = createMockRepository()
        mockRepo.fetchPerson = jest.fn().mockImplementation(() => {
            return Promise.resolve(sharedPerson)
        })
        const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

        // Update via first distinct ID - unset 'conflicting_prop'
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            {},
            ['conflicting_prop'],
            {},
            distinctId1
        )

        // Update via second distinct ID - set 'conflicting_prop' (should win over unset)
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            { conflicting_prop: 'new_value' },
            [],
            {},
            distinctId2
        )

        const cache = personStore.getUpdateCache()
        const cacheValue = cache.get(`${teamId}:${sharedPerson.id}`)

        expect(cacheValue).toBeDefined()
        // The set should win - property should be in properties_to_set and NOT in properties_to_unset
        expect(cacheValue?.properties_to_set).toEqual({
            existing_prop: 'existing_value',
            conflicting_prop: 'new_value',
        })
        expect(cacheValue?.properties_to_unset).toEqual([])

        await personStore.flush()

        // In NO_ASSERT mode, we use batch updates
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    properties_to_set: {
                        existing_prop: 'existing_value',
                        conflicting_prop: 'new_value',
                    },
                    properties_to_unset: [],
                }),
            ])
        )
    })

    it('should handle unset after set conflicts when merging updates for same person via different distinct IDs', async () => {
        // This test validates that when two distinct IDs point to the same person,
        // and one sets a property while the other unsets it (in that order), the unset wins
        const distinctId1 = 'user-email@example.com'
        const distinctId2 = 'user-device-abc123'

        const sharedPerson = {
            ...person,
            properties: {
                existing_prop: 'existing_value',
            },
        }

        const mockRepo = createMockRepository()
        mockRepo.fetchPerson = jest.fn().mockImplementation(() => {
            return Promise.resolve(sharedPerson)
        })
        const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

        // Update via first distinct ID - set 'conflicting_prop'
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            { conflicting_prop: 'some_value' },
            [],
            {},
            distinctId1
        )

        // Update via second distinct ID - unset 'conflicting_prop' (should win over set)
        await personStore.updatePersonWithPropertiesDiffForUpdate(
            sharedPerson,
            {},
            ['conflicting_prop'],
            {},
            distinctId2
        )

        const cache = personStore.getUpdateCache()
        const cacheValue = cache.get(`${teamId}:${sharedPerson.id}`)

        expect(cacheValue).toBeDefined()
        // The unset should win - property should be in properties_to_unset and NOT in properties_to_set
        expect(cacheValue?.properties_to_set).toEqual({
            existing_prop: 'existing_value',
        })
        expect(cacheValue?.properties_to_unset).toEqual(['conflicting_prop'])

        await personStore.flush()

        // In NO_ASSERT mode, we use batch updates
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    properties_to_set: {
                        existing_prop: 'existing_value',
                    },
                    properties_to_unset: ['conflicting_prop'],
                }),
            ])
        )
    })

    describe('moveDistinctIds', () => {
        it('should preserve cached merged properties when moving distinct IDs', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

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
            personStore.setCachedPersonForUpdate(
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
            await personStore.updatePersonForMerge(targetPerson, mergeUpdate, 'target-distinct')

            // Verify the merge worked - check the final computed result
            const cacheAfterMerge = personStore.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
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
            const tx = createMockTransaction() as any
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx)

            // Verify the repository method was called
            // moveDistinctIds is executed via tx, not repo
            expect(tx.moveDistinctIds).toHaveBeenCalledTimes(1)
            expect(tx.moveDistinctIds).toHaveBeenCalledWith(sourcePerson, targetPerson, undefined)

            // Step 4: Verify that cached merged properties are preserved
            const cacheAfterMove = personStore.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
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
            const sourceCacheAfterMove = personStore.getCachedPersonForUpdateByPersonId(teamId, sourcePerson.id)
            expect(sourceCacheAfterMove).toBeUndefined()
        })

        it('should create fresh cache when no existing cache exists', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

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
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, targetPerson.id)).toBeUndefined()

            // Move distinct IDs
            const tx = createMockTransaction() as any
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx)

            // Verify the repository method was called
            expect(tx.moveDistinctIds).toHaveBeenCalledTimes(1)
            expect(tx.moveDistinctIds).toHaveBeenCalledWith(sourcePerson, targetPerson, undefined)

            // Should create fresh cache from target person
            const cacheAfterMove = personStore.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
            expect(cacheAfterMove?.properties).toEqual({
                target_prop: 'target_value',
            })
            expect(cacheAfterMove?.id).toBe(targetPerson.id)
            expect(cacheAfterMove?.distinct_id).toBe('target-distinct')
        })

        it('should clear source person cache', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

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
            personStore.setCachedPersonForUpdate(
                teamId,
                'source-distinct',
                fromInternalPerson(sourcePerson, 'source-distinct')
            )

            // Verify source cache exists
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, sourcePerson.id)).toBeDefined()

            // Move distinct IDs
            const tx = createMockTransaction() as any
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx)

            // Verify the repository method was called
            expect(tx.moveDistinctIds).toHaveBeenCalledTimes(1)
            expect(tx.moveDistinctIds).toHaveBeenCalledWith(sourcePerson, targetPerson, undefined)

            // Verify source cache is cleared
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, sourcePerson.id)).toBeUndefined()
        })

        it('should handle complex merge scenario with multiple properties', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

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
            personStore.setCachedPersonForUpdate(
                teamId,
                'target-distinct',
                fromInternalPerson(targetPerson, 'target-distinct')
            )

            // Step 2: Multiple merge operations
            await personStore.updatePersonForMerge(
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

            await personStore.updatePersonForMerge(
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
            const tx = createMockTransaction() as any
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx)

            // Verify the repository method was called
            expect(tx.moveDistinctIds).toHaveBeenCalledTimes(1)
            expect(tx.moveDistinctIds).toHaveBeenCalledWith(sourcePerson, targetPerson, undefined)

            // Step 4: Verify all merged properties are preserved
            const finalCache = personStore.getCachedPersonForUpdateByDistinctId(teamId, 'target-distinct')
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

    describe('addPersonlessDistinctId', () => {
        it('should call repository method and return result', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const result = await personStore.addPersonlessDistinctId(teamId, 'test-distinct')

            expect(mockRepo.addPersonlessDistinctId).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(true)
        })

        it('should handle repository returning false', async () => {
            const mockRepo = createMockRepository()
            mockRepo.addPersonlessDistinctId = jest.fn().mockResolvedValue(false)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const result = await personStore.addPersonlessDistinctId(teamId, 'test-distinct')

            expect(mockRepo.addPersonlessDistinctId).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(false)
        })
    })

    describe('addPersonlessDistinctIdForMerge', () => {
        it('should call repository method and return result', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const result = await personStore.addPersonlessDistinctIdForMerge(teamId, 'test-distinct')

            expect(mockRepo.addPersonlessDistinctIdForMerge).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(true)
        })

        it('should handle repository returning false', async () => {
            const mockRepo = createMockRepository()
            mockRepo.addPersonlessDistinctIdForMerge = jest.fn().mockResolvedValue(false)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const result = await personStore.addPersonlessDistinctIdForMerge(teamId, 'test-distinct')

            expect(mockRepo.addPersonlessDistinctIdForMerge).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(false)
        })
    })

    describe('personPropertiesSize', () => {
        it('should call repository method and return result', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)
            const personId = 'test-person-id'
            const teamId = 1

            const result = await personStore.personPropertiesSize(personId, teamId)

            expect(mockRepo.personPropertiesSize).toHaveBeenCalledWith(personId, teamId)
            expect(result).toBe(1024)
        })

        it('should handle repository returning 0', async () => {
            const mockRepo = createMockRepository()
            mockRepo.personPropertiesSize = jest.fn().mockResolvedValue(0)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)
            const personId = 'test-person-id'
            const teamId = 1

            const result = await personStore.personPropertiesSize(personId, teamId)

            expect(mockRepo.personPropertiesSize).toHaveBeenCalledWith(personId, teamId)
            expect(result).toBe(0)
        })
    })

    describe('updateCohortsAndFeatureFlagsForMerge', () => {
        it('should call repository method with correct arguments', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const teamID = 1
            const sourcePersonID = 'source-person-id'
            const targetPersonID = 'target-person-id'
            const distinctId = 'test-distinct'

            await personStore.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, distinctId)

            expect(mockRepo.updateCohortsAndFeatureFlagsForMerge).toHaveBeenCalledWith(
                teamID,
                sourcePersonID,
                targetPersonID
            )
        })

        it('should call repository method with transaction when provided', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const teamID = 1
            const sourcePersonID = 'source-person-id'
            const targetPersonID = 'target-person-id'
            const distinctId = 'test-distinct'

            const mockTransaction = createMockTransaction()

            await personStore.updateCohortsAndFeatureFlagsForMerge(
                teamID,
                sourcePersonID,
                targetPersonID,
                distinctId,
                mockTransaction
            )

            // Verify the transaction was called instead of the repository
            expect(mockTransaction.updateCohortsAndFeatureFlagsForMerge).toHaveBeenCalledWith(
                teamID,
                sourcePersonID,
                targetPersonID
            )

            // Verify the repository was NOT called
            expect(mockRepo.updateCohortsAndFeatureFlagsForMerge).not.toHaveBeenCalled()
        })
    })

    describe('property filtering at batch level', () => {
        const mockPersonProfileBatchUpdateOutcomeCounter = personProfileBatchUpdateOutcomeCounter as jest.Mocked<
            typeof personProfileBatchUpdateOutcomeCounter
        >
        const mockPersonProfileBatchIgnoredPropertiesCounter =
            personProfileBatchIgnoredPropertiesCounter as jest.Mocked<typeof personProfileBatchIgnoredPropertiesCounter>
        const mockPersonPropertyKeyUpdateCounter = personPropertyKeyUpdateCounter as jest.Mocked<
            typeof personPropertyKeyUpdateCounter
        >

        it('should skip database write when only filtered properties are updated', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Update person with only filtered properties (existing properties being updated)
            // Using $current_url and $pathname which are in FILTERED_PERSON_UPDATE_PROPERTIES
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                { ...person, properties: { $current_url: 'https://old.com', $pathname: '/old' } },
                { $current_url: 'https://new.com', $pathname: '/new' },
                [],
                {},
                'test'
            )

            // Flush should skip the database write since only filtered properties changed
            await personStore.flush()

            expect(mockRepo.updatePerson).not.toHaveBeenCalled()
            expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()

            // Verify metrics
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'ignored' }).inc).toHaveBeenCalledTimes(
                1
            )
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledTimes(2)
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$current_url',
            })
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$pathname',
            })
            // personPropertyKeyUpdateCounter should NOT be called for 'ignored' outcomes
            expect(mockPersonPropertyKeyUpdateCounter.labels).not.toHaveBeenCalled()
        })

        it('should skip database write when only blocked $geoip_* properties are updated', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Update person with only blocked geoip properties (existing properties being updated)
            // Note: $geoip_country_name and $geoip_city_name are allowed, but $geoip_latitude is blocked
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                { ...person, properties: { $geoip_latitude: 40.7128, $geoip_longitude: -74.006 } },
                { $geoip_latitude: 37.7749, $geoip_longitude: -74.006 },
                [],
                {},
                'test'
            )

            // Flush should skip the database write
            await personStore.flush()

            expect(mockRepo.updatePerson).not.toHaveBeenCalled()
            expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()

            // Verify metrics
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'ignored' }).inc).toHaveBeenCalledTimes(
                1
            )
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$geoip_latitude',
            })
            // personPropertyKeyUpdateCounter should NOT be called for 'ignored' outcomes
            expect(mockPersonPropertyKeyUpdateCounter.labels).not.toHaveBeenCalled()
        })

        it('should write to database when filtered properties are NEW (not in existing properties)', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Person without browser property
            const personWithoutBrowser = { ...person, properties: { name: 'John' } }

            // Update person with NEW eventToPersonProperty
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithoutBrowser,
                { $browser: 'Chrome' },
                [],
                {},
                'test'
            )

            // Flush SHOULD write to database since it's a new property
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)

            // Verify metrics - should be 'changed' since new property triggers write
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalledTimes(
                1
            )
            // Note: $browser would be ignored at event level (see person-update.ts), but filtering happens at batch level
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            // personPropertyKeyUpdateCounter should be called for new property
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$browser' })
            expect(mockPersonPropertyKeyUpdateCounter.labels({ key: '$browser' }).inc).toHaveBeenCalledTimes(1)
        })

        it('should write to database when mixing filtered and non-filtered properties', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Update person with both filtered and non-filtered properties
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                { ...person, properties: { $browser: 'Firefox', name: 'Jane' } },
                { $browser: 'Chrome', name: 'John' },
                [],
                {},
                'test'
            )

            // Flush SHOULD write to database because name is not filtered
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)

            // Verify metrics - should be 'changed' since non-filtered property triggers write
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalledTimes(
                1
            )
            // Note: $browser would be ignored at event level (see person-update.ts), but filtering happens at batch level
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            // personPropertyKeyUpdateCounter should be called for both properties
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledTimes(2)
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$browser' })
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: 'other' })
        })

        it('should write to database when unsetting any property', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Unset a filtered property
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                { ...person, properties: { $browser: 'Chrome' } },
                {},
                ['$browser'],
                {},
                'test'
            )

            // Flush SHOULD write to database because unsetting always triggers a write
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)

            // Verify metrics - should be 'changed' since unsetting triggers write
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalledTimes(
                1
            )
            // Note: $browser would be ignored at event level (see person-update.ts), but filtering happens at batch level
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            // personPropertyKeyUpdateCounter should be called for unset property
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$browser' })
            expect(mockPersonPropertyKeyUpdateCounter.labels({ key: '$browser' }).inc).toHaveBeenCalledTimes(1)
        })

        it('should write to database when force_update is set even with only filtered properties', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Update person with only filtered properties but with force_update=true (simulating $identify/$set events)
            // Using $current_url and $pathname which are in FILTERED_PERSON_UPDATE_PROPERTIES
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                { ...person, properties: { $current_url: 'https://old.com', $pathname: '/old' } },
                { $current_url: 'https://new.com', $pathname: '/new' },
                [],
                {},
                'test',
                true // force_update=true for $identify/$set events
            )

            // Flush SHOULD write to database because force_update bypasses filtering
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)

            // Verify metrics - should be 'changed' because force_update bypasses filtering
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalledTimes(
                1
            )
            // With force_update, properties should not be marked as ignored
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            // personPropertyKeyUpdateCounter should be called for the updated properties
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledTimes(2)
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$current_url' })
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$pathname' })
        })

        it('integration: multiple events with only filtered properties should not trigger database write', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Using properties that are in FILTERED_PERSON_UPDATE_PROPERTIES
            const personWithFiltered = {
                ...person,
                properties: {
                    $current_url: 'https://old.com',
                    $pathname: '/old',
                    $geoip_latitude: 40.7128,
                },
            }

            // Event 1: Update current_url (filtered)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $current_url: 'https://new.com' },
                [],
                {},
                'test'
            )

            // Event 2: Update pathname (filtered)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $pathname: '/new' },
                [],
                {},
                'test'
            )

            // Event 3: Update blocked geoip property (latitude is blocked, city_name is allowed)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $geoip_latitude: 37.7749 },
                [],
                {},
                'test'
            )

            // Flush should NOT write to database - all properties are filtered
            await personStore.flush()

            expect(mockRepo.updatePerson).not.toHaveBeenCalled()
            expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()

            // Verify metrics - should be 'ignored' since all properties are filtered
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'ignored' }).inc).toHaveBeenCalledTimes(
                1
            )
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledTimes(3)
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$current_url',
            })
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$pathname',
            })
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$geoip_latitude',
            })
            // personPropertyKeyUpdateCounter should NOT be called for 'ignored' outcomes
            expect(mockPersonPropertyKeyUpdateCounter.labels).not.toHaveBeenCalled()
        })

        it('should write to database when allowed geoip property ($geoip_country_name) is updated alongside blocked ones', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Person with existing geoip properties
            const personWithGeoip = {
                ...person,
                properties: {
                    $geoip_country_name: 'Canada',
                    $geoip_city_name: 'Toronto',
                    $geoip_latitude: 43.6532,
                    $geoip_longitude: -79.3832,
                },
            }

            // Update all geoip properties including allowed ones (country_name, city_name)
            // Since $geoip_country_name is allowed, all properties should be updated
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithGeoip,
                {
                    $geoip_country_name: 'United States',
                    $geoip_city_name: 'San Francisco',
                    $geoip_latitude: 37.7749,
                    $geoip_longitude: -122.4194,
                },
                [],
                {},
                'test'
            )

            // Flush SHOULD write to database because $geoip_country_name is allowed
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith([
                expect.objectContaining({
                    properties_to_set: {
                        $geoip_country_name: 'United States',
                        $geoip_city_name: 'San Francisco',
                        $geoip_latitude: 37.7749,
                        $geoip_longitude: -122.4194,
                    },
                }),
            ])

            // Verify metrics - should be 'changed' since allowed geoip property triggers write
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            // personPropertyKeyUpdateCounter uses getMetricKey which returns 'geoIP' for all $geoip_* properties
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: 'geoIP' })
        })

        it('integration: filtered properties then non-filtered property should trigger database write', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const personWithFiltered = {
                ...person,
                properties: {
                    $browser: 'Firefox',
                    $app_build: '100',
                    $os: 'Windows',
                    name: 'Jane',
                },
            }

            // Event 1: Update browser (filtered)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $browser: 'Chrome' },
                [],
                {},
                'test'
            )

            // Event 2: Update app build (filtered)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $app_build: '200' },
                [],
                {},
                'test'
            )

            // Event 3: Update name (NOT filtered)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { name: 'John' },
                [],
                {},
                'test'
            )

            // Event 4: Update more filtered properties
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $os: 'macOS' },
                [],
                {},
                'test'
            )

            // Flush SHOULD write to database because event 3 has non-filtered property
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith([
                expect.objectContaining({
                    properties_to_set: {
                        $browser: 'Chrome',
                        $app_build: '200',
                        $os: 'macOS',
                        name: 'John',
                    },
                }),
            ])

            // Verify metrics - should be 'changed' since non-filtered property triggers write
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalledTimes(
                1
            )
            // Note: some properties would be ignored at event level (see person-update.ts), but filtering happens at batch level
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            // personPropertyKeyUpdateCounter should be called for all 4 properties
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledTimes(4)
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$browser' })
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$app_build' })
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: '$os' })
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: 'other' })
        })

        it('integration: normal events for regression - custom properties always trigger writes', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Event 1: Normal custom property
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { plan: 'premium' }, [], {}, 'test')

            // Event 2: Another custom property
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                person,
                { subscription_status: 'active' },
                [],
                {},
                'test'
            )

            // Flush SHOULD write to database
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith([
                expect.objectContaining({
                    properties_to_set: expect.objectContaining({
                        plan: 'premium',
                        subscription_status: 'active',
                    }),
                }),
            ])

            // Verify metrics - should be 'changed' since custom properties trigger write
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalledTimes(
                1
            )
            // Note: custom properties are never ignored at event level (see person-update.ts)
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            // personPropertyKeyUpdateCounter should be called once for 'other' (deduplicated by Set)
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonPropertyKeyUpdateCounter.labels).toHaveBeenCalledWith({ key: 'other' })
            expect(mockPersonPropertyKeyUpdateCounter.labels({ key: 'other' }).inc).toHaveBeenCalledTimes(1)
        })

        it('integration: chain of events - normal event (ignored), $identify event (forces update), then normal event (also written)', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            const personWithFiltered = {
                ...person,
                properties: {
                    $browser: 'Firefox',
                    utm_source: 'twitter',
                    $geoip_city_name: 'New York',
                },
            }

            // Event 1: Normal pageview event with filtered properties
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $browser: 'Chrome', utm_source: 'google' },
                [],
                {},
                'test'
            )

            // Event 2: $identify event with ONLY filtered properties - should force update
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $geoip_city_name: 'San Francisco', $browser: 'Safari' },
                [],
                {},
                'test',
                true // forceUpdate=true ($identify event)
            )

            // Event 3: Another normal event with filtered properties
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { utm_source: 'facebook' },
                [],
                {},
                'test'
            )

            // Flush SHOULD write to database because $identify event set force_update=true
            await personStore.flush()

            // In NO_ASSERT mode, we use batch updates
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)

            // Verify that ALL property changes from all three events are written
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith([
                expect.objectContaining({
                    properties_to_set: expect.objectContaining({
                        $browser: 'Safari',
                        utm_source: 'facebook',
                        $geoip_city_name: 'San Francisco',
                    }),
                }),
            ])
        })

        it('integration: chain without $identify/$set should not trigger update', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockKafkaProducer)

            // Using properties that are in FILTERED_PERSON_UPDATE_PROPERTIES
            const personWithFiltered = {
                ...person,
                properties: {
                    $current_url: 'https://old.com',
                    $pathname: '/old',
                },
            }

            // Event 1: Normal event with filtered properties
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $current_url: 'https://new.com' },
                [],
                {},
                'test'
                // forceUpdate not set
            )

            // Event 2: Another normal event with filtered properties
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $pathname: '/new' },
                [],
                {},
                'test'
                // forceUpdate not set
            )

            // Event 3: Yet another normal event with filtered properties
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithFiltered,
                { $current_url: 'https://another.com' },
                [],
                {},
                'test'
                // forceUpdate not set
            )

            // Flush should NOT write to database - all events are normal with only filtered properties
            await personStore.flush()

            expect(mockRepo.updatePerson).not.toHaveBeenCalled()
            expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()

            // Verify metrics - should be 'ignored' since all properties are filtered and no force_update
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels({ outcome: 'ignored' }).inc).toHaveBeenCalledTimes(
                1
            )
            // Properties should be marked as ignored
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledTimes(2)
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$current_url',
            })
            expect(mockPersonProfileBatchIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                property: '$pathname',
            })
            // personPropertyKeyUpdateCounter should NOT be called for 'ignored' outcomes
            expect(mockPersonPropertyKeyUpdateCounter.labels).not.toHaveBeenCalled()
        })
    })

    describe('reset', () => {
        it('should clear all caches and metrics after reset', async () => {
            const personStore = getPersonsStore()

            // Populate caches by fetching and updating a person
            await personStore.fetchForUpdate(teamId, 'distinct-1')
            await personStore.fetchForChecking(teamId, 'distinct-2')
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { name: 'test' }, [], {}, 'distinct-1')

            // Verify caches are populated
            expect(personStore.getUpdateCache().size).toBeGreaterThan(0)
            expect(personStore.getCheckCache().size).toBeGreaterThan(0)

            // Reset the store
            personStore.reset()

            // Verify all caches are cleared
            expect(personStore.getUpdateCache().size).toBe(0)
            expect(personStore.getCheckCache().size).toBe(0)
        })

        it('should allow reuse of the store after reset', async () => {
            const personStore = getPersonsStore()

            // First batch: populate and flush
            await personStore.fetchForUpdate(teamId, 'distinct-1')
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { batch: '1' }, [], {}, 'distinct-1')
            await personStore.flush()
            personStore.reportBatch()
            personStore.reset()

            // Second batch: should work normally without stale data
            const person2 = { ...person, id: '2', properties: { original: 'value' } }
            mockRepo.fetchPerson.mockResolvedValueOnce(person2)

            await personStore.fetchForUpdate(teamId, 'distinct-2')
            await personStore.updatePersonWithPropertiesDiffForUpdate(person2, { batch: '2' }, [], {}, 'distinct-2')
            await personStore.flush()

            // Verify second batch wrote correctly (NO_ASSERT mode uses batch updates)
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(2)
            expect(mockRepo.updatePersonsBatch).toHaveBeenLastCalledWith([
                expect.objectContaining({
                    properties_to_set: expect.objectContaining({ batch: '2' }),
                }),
            ])
        })

        it('should not share cached person data between batches', async () => {
            const personStore = getPersonsStore()

            // First batch: cache person with specific properties
            const personBatch1 = { ...person, properties: { name: 'Batch1Person' } }
            mockRepo.fetchPerson.mockResolvedValueOnce(personBatch1)

            await personStore.fetchForUpdate(teamId, 'user-1')
            await personStore.flush()
            personStore.reportBatch()
            personStore.reset()

            // Second batch: same distinct_id should fetch fresh from DB
            const personBatch2 = { ...person, properties: { name: 'Batch2Person', newProp: 'value' } }
            mockRepo.fetchPerson.mockResolvedValueOnce(personBatch2)

            const fetchedPerson = await personStore.fetchForUpdate(teamId, 'user-1')

            // Should have fetched from DB again, not used stale cache
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(2)
            expect(fetchedPerson?.properties).toEqual({ name: 'Batch2Person', newProp: 'value' })
        })
    })

    describe('createPerson caching', () => {
        it('should cache all extra distinct IDs when creating a person with multiple distinct IDs', async () => {
            const personStore = getPersonsStore()
            const createdPerson = { ...person, uuid: 'new-uuid' }
            mockRepo.createPerson.mockResolvedValue({
                success: true,
                person: createdPerson,
                messages: [],
                created: true,
            })

            await personStore.createPerson(
                DateTime.now(),
                { prop: 'value' },
                {},
                {},
                teamId,
                null,
                false,
                'new-uuid',
                { distinctId: 'primary-id' },
                [{ distinctId: 'extra-id-1' }, { distinctId: 'extra-id-2' }, { distinctId: 'extra-id-3' }]
            )

            // All distinct IDs should be cached - verify by checking the cache directly
            const checkCache = personStore.getCheckCache()
            const updateCache = personStore.getUpdateCache()

            // Primary distinct ID should be cached
            expect(checkCache.get(`${teamId}:primary-id`)).toEqual(createdPerson)
            expect(updateCache.get(`${teamId}:${createdPerson.id}`)).toBeDefined()

            // All extra distinct IDs should also be cached for update lookups
            // The distinctIdToPersonId map should contain all extra distinct IDs
            const distinctIdToPersonId = (personStore as any).distinctIdToPersonId as Map<string, string>
            expect(distinctIdToPersonId.get(`${teamId}:extra-id-1`)).toBe(createdPerson.id)
            expect(distinctIdToPersonId.get(`${teamId}:extra-id-2`)).toBe(createdPerson.id)
            expect(distinctIdToPersonId.get(`${teamId}:extra-id-3`)).toBe(createdPerson.id)
        })
    })

    describe('prefetchPersons', () => {
        it('should fetch persons in a single batched query and populate both caches', async () => {
            const personStoreForBatch = getPersonsStore()

            const person1 = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }
            const person2 = { ...person, id: '2', team_id: teamId, distinct_id: 'user-2' }

            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([person1, person2])

            await personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1' },
                { teamId, distinctId: 'user-2' },
            ])

            // Should have called fetchPersonsByDistinctIds once with both entries (useReadReplica=false)
            expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalledTimes(1)
            expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalledWith(
                [
                    { teamId, distinctId: 'user-1' },
                    { teamId, distinctId: 'user-2' },
                ],
                false
            )

            // Both caches should be populated (check cache stores InternalPerson without distinct_id)
            const { distinct_id: _1, ...expectedPerson1 } = person1
            const { distinct_id: _2, ...expectedPerson2 } = person2
            expect(personStoreForBatch.getCheckCache().get(`${teamId}:user-1`)).toEqual(expectedPerson1)
            expect(personStoreForBatch.getCheckCache().get(`${teamId}:user-2`)).toEqual(expectedPerson2)
            expect(personStoreForBatch.getUpdateCache().get(`${teamId}:1`)).toBeDefined()
            expect(personStoreForBatch.getUpdateCache().get(`${teamId}:2`)).toBeDefined()
        })

        it('should cache null in check cache only for persons not found', async () => {
            const personStoreForBatch = getPersonsStore()

            const person1 = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }

            // Only return person1, not person2
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([person1])

            await personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1' },
                { teamId, distinctId: 'user-2' },
            ])

            // Check cache: person1 should be cached (without distinct_id), person2 should be null
            const { distinct_id: _, ...expectedPerson1 } = person1
            expect(personStoreForBatch.getCheckCache().get(`${teamId}:user-1`)).toEqual(expectedPerson1)
            expect(personStoreForBatch.getCheckCache().get(`${teamId}:user-2`)).toBeNull()

            // Update cache: only person1 should be cached (no null for missing)
            expect(personStoreForBatch.getUpdateCache().get(`${teamId}:1`)).toBeDefined()
            expect(personStoreForBatch.getUpdateCache().has(`${teamId}:2`)).toBe(false)
        })

        it('should skip entries already in check cache', async () => {
            const personStoreForBatch = getPersonsStore()

            // Pre-populate check cache for user-1
            const existingPerson = { ...person, id: '1', team_id: teamId }
            personStoreForBatch.getCheckCache().set(`${teamId}:user-1`, existingPerson)

            const person2 = { ...person, id: '2', team_id: teamId, distinct_id: 'user-2' }
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([person2])

            await personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1' },
                { teamId, distinctId: 'user-2' },
            ])

            // Should only fetch user-2 since user-1 was already cached
            expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalledWith([{ teamId, distinctId: 'user-2' }], false)
        })

        it('should skip entries already in update cache', async () => {
            const personStoreForBatch = getPersonsStore()

            // Pre-populate by fetching for update
            mockRepo.fetchPerson.mockResolvedValueOnce(person)
            await personStoreForBatch.fetchForUpdate(teamId, 'user-1')

            const person2 = { ...person, id: '2', team_id: teamId, distinct_id: 'user-2' }
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([person2])

            await personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1' },
                { teamId, distinctId: 'user-2' },
            ])

            // Should only fetch user-2 since user-1 was already in update cache
            expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalledWith([{ teamId, distinctId: 'user-2' }], false)
        })

        it('should do nothing for empty input', async () => {
            const personStoreForBatch = getPersonsStore()

            await personStoreForBatch.prefetchPersons([])

            expect(mockRepo.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('should do nothing when all entries are already cached', async () => {
            const personStoreForBatch = getPersonsStore()

            // Pre-populate cache
            personStoreForBatch.getCheckCache().set(`${teamId}:user-1`, person)
            personStoreForBatch.getCheckCache().set(`${teamId}:user-2`, null)

            await personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1' },
                { teamId, distinctId: 'user-2' },
            ])

            expect(mockRepo.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('should allow fetchForChecking to use prefetched data', async () => {
            const personStoreForBatch = getPersonsStore()

            const prefetchedPerson = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([prefetchedPerson])

            await personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1' }])

            // Now fetchForChecking should use cached data
            const result = await personStoreForBatch.fetchForChecking(teamId, 'user-1')

            // Result is InternalPerson (no distinct_id), so compare without it
            const { distinct_id: _, ...expectedPerson } = prefetchedPerson
            expect(result).toEqual(expectedPerson)
            // fetchPerson should not have been called since data was prefetched
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
        })

        it('should allow fetchForUpdate to use prefetched data', async () => {
            const personStoreForBatch = getPersonsStore()

            const prefetchedPerson = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([prefetchedPerson])

            await personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1' }])

            // Now fetchForUpdate should use cached data
            const result = await personStoreForBatch.fetchForUpdate(teamId, 'user-1')

            // Result is InternalPerson (no distinct_id), so compare without it
            const { distinct_id: _, ...expectedPerson } = prefetchedPerson
            expect(result).toEqual(expectedPerson)
            // fetchPerson should not have been called since data was prefetched
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
        })

        it('should allow fetchForChecking to wait on in-flight prefetch without duplicate queries', async () => {
            const personStoreForBatch = getPersonsStore()

            const prefetchedPerson = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }

            // Create a deferred promise so we can control when the prefetch completes
            let resolvePrefetch: (value: (typeof prefetchedPerson)[]) => void
            const prefetchPromise = new Promise<(typeof prefetchedPerson)[]>((resolve) => {
                resolvePrefetch = resolve
            })
            mockRepo.fetchPersonsByDistinctIds.mockReturnValueOnce(prefetchPromise)

            // Start prefetch but don't await it (simulating non-blocking behavior)
            const prefetchCompletion = personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1' }])

            // Now call fetchForChecking while prefetch is still in flight
            const fetchCheckingPromise = personStoreForBatch.fetchForChecking(teamId, 'user-1')

            // Resolve the prefetch
            resolvePrefetch!([prefetchedPerson])
            await prefetchCompletion

            // fetchForChecking should get the prefetched data
            const result = await fetchCheckingPromise

            const { distinct_id: _, ...expectedPerson } = prefetchedPerson
            expect(result).toEqual(expectedPerson)

            // Only the batch fetch should have been called, not individual fetchPerson
            expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalledTimes(1)
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
        })

        it('should allow fetchForUpdate to wait on in-flight prefetch without duplicate queries', async () => {
            const personStoreForBatch = getPersonsStore()

            const prefetchedPerson = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }

            // Create a deferred promise so we can control when the prefetch completes
            let resolvePrefetch: (value: (typeof prefetchedPerson)[]) => void
            const prefetchPromise = new Promise<(typeof prefetchedPerson)[]>((resolve) => {
                resolvePrefetch = resolve
            })
            mockRepo.fetchPersonsByDistinctIds.mockReturnValueOnce(prefetchPromise)

            // Start prefetch but don't await it
            const prefetchCompletion = personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1' }])

            // Now call fetchForUpdate while prefetch is still in flight
            const fetchUpdatePromise = personStoreForBatch.fetchForUpdate(teamId, 'user-1')

            // Resolve the prefetch
            resolvePrefetch!([prefetchedPerson])
            await prefetchCompletion

            // fetchForUpdate should get the prefetched data
            const result = await fetchUpdatePromise

            const { distinct_id: _, ...expectedPerson } = prefetchedPerson
            expect(result).toEqual(expectedPerson)

            // Only the batch fetch should have been called, not individual fetchPerson
            expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalledTimes(1)
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
        })
    })
})
