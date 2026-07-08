import { DateTime } from 'luxon'

import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { PERSONS_OUTPUT, PersonDistinctIdsOutput, PersonMergeEventsOutput, PersonsOutput } from '~/common/outputs'
import {
    personProfileBatchIgnoredPropertiesCounter,
    personProfileBatchUpdateOutcomeCounter,
    personPropertyKeyUpdateCounter,
} from '~/common/persons/metrics'
import { fromInternalPerson } from '~/common/persons/person-update-batch'
import { DependencyUnavailableError, MessageSizeTooLarge } from '~/common/utils/db/error'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { InternalPerson, TeamId } from '~/types'

import { BatchWritingPersonsStore } from './batch-writing-person-store'
import { BatchBoundPersonsStore } from './persons-store-for-batch'

// Mock the ingestion warnings module
jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

// Mock metrics
jest.mock('~/common/persons/metrics', () => ({
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
    let mockIngestionWarningsOutputs: jest.Mocked<
        ReturnType<
            typeof createMockIngestionOutputs<
                PersonsOutput | PersonDistinctIdsOutput | typeof INGESTION_WARNINGS_OUTPUT | PersonMergeEventsOutput
            >
        >
    >
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
            last_seen_at: null,
        }

        mockPostgres = {
            transaction: jest.fn().mockImplementation(async (_usage, _tag, transaction) => {
                return await transaction(transaction)
            }),
        } as unknown as PostgresRouter

        mockIngestionWarningsOutputs = createMockIngestionOutputs<
            PersonsOutput | PersonDistinctIdsOutput | typeof INGESTION_WARNINGS_OUTPUT | PersonMergeEventsOutput
        >()

        mockRepo = createMockRepository()
        personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)
    })

    afterEach(async () => {
        // Clear the metric-emission interval started in the constructor;
        // unref() prevents it from blocking process exit, but we still want
        // a clean slate between tests. Tests may leave dirty entries behind,
        // so flush first — shutdown() throws on dirty cache by design.
        try {
            await personStore?.flush()
        } catch {
            // ignore — some tests intentionally fail flush
        }
        try {
            await personStore?.shutdown()
        } catch {
            // ignore — some tests intentionally leave the cache dirty
        }
        jest.clearAllMocks()
    })

    afterAll(() => {
        // resetAllMocks resets mock implementations (not just call history),
        // preventing throwing mocks from leaking into subsequent test files
        // when running in the same Jest worker process (--runInBand).
        jest.resetAllMocks()
    })

    const getPersonsStore = () => personStore

    const createMockRepository = () => {
        const mockRepo = {
            fetchPerson: jest.fn().mockResolvedValue(person),
            fetchPersonDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
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
                        kafkaMessage: undefined,
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
        const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
            const personFromCheck = await personStore.fetchForChecking(teamId, 'test-distinct', 0)
            expect(personFromCheck).toEqual(person)

            const checkCache = (personStore as any)['personCheckCache']
            expect(checkCache.get('1:test-distinct')).toEqual(person)

            // Fetch for update should cache in update cache and return PersonUpdate converted to InternalPerson
            const personFromUpdate = await personStore.fetchForUpdate(teamId, 'test-distinct2', 0)
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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            // First fetch should hit the database
            await personStore.fetchForChecking(teamId, 'test-distinct', 0)
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1)

            // Second fetch should hit the cache
            await personStore.fetchForChecking(teamId, 'test-distinct', 0)
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1) // No additional call

            // Similar for update cache
            await personStore.fetchForUpdate(teamId, 'test-distinct2', 0)
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(2)

            await personStore.fetchForUpdate(teamId, 'test-distinct2', 0)
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(2) // No additional call
        })

        it('should prefer update cache over check cache in fetchForChecking', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            // First populate update cache
            await personStore.fetchForUpdate(teamId, 'test-distinct', 0)

            // Reset the mock to track new calls
            jest.clearAllMocks()

            // fetchForChecking should use the cached PersonUpdate instead of hitting DB
            const result = await personStore.fetchForChecking(teamId, 'test-distinct', 0)
            expect(result).toBeDefined()
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
        })

        it('should handle null results from database', async () => {
            const mockRepo = createMockRepository()
            mockRepo.fetchPerson = jest.fn().mockResolvedValue(undefined)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const checkResult = await personStore.fetchForChecking(teamId, 'nonexistent', 0)
            expect(checkResult).toBeNull()

            const updateResult = await personStore.fetchForUpdate(teamId, 'nonexistent', 0)
            expect(updateResult).toBeNull()
        })
    })

    it('should retry optimistic updates with exponential backoff', async () => {
        // Use ASSERT_VERSION mode for this test since it tests optimistic behavior
        const testMockRepo = createMockRepository()
        const assertVersionStore = new BatchWritingPersonsStore(testMockRepo, mockIngestionWarningsOutputs, {
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
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
        const originalUpdatePersonsBatch = mockRepo.updatePersonsBatch
        // Mock batch update to throw an error - all persons will fail
        mockRepo.updatePersonsBatch = jest.fn().mockImplementation(() => {
            throw new Error('Database connection failed')
        })

        try {
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_value: 'new_value' },
                [],
                {},
                'test'
            )

            await expect(personStore.flush()).rejects.toThrow('Database connection failed')
        } finally {
            mockRepo.updatePersonsBatch = originalUpdatePersonsBatch
        }
    })

    it('should handle partial failures in batch flush', async () => {
        const originalUpdatePersonsBatch = mockRepo.updatePersonsBatch
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
        const originalUpdatePerson = mockRepo.updatePerson
        mockRepo.updatePerson = jest.fn().mockRejectedValue(new Error('Database error'))

        try {
            await expect(personStore.flush()).rejects.toThrow('Database error')
        } finally {
            mockRepo.updatePersonsBatch = originalUpdatePersonsBatch
            mockRepo.updatePerson = originalUpdatePerson
        }
    })

    it('should handle clearing cache for different team IDs', async () => {
        const mockRepo = createMockRepository()
        const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)
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
        expect(emitIngestionWarning).toHaveBeenCalledWith(mockIngestionWarningsOutputs, teamId, {
            type: 'person_upsert_message_size_too_large',
            details: {
                personId: person.uuid,
                distinctId: 'test',
            },
            category: 'size',
            severity: 'error',
            pipelineStep: 'person-store',
        })
    })

    describe('dbWriteMode functionality', () => {
        describe('flush with NO_ASSERT mode', () => {
            it('should call updatePersonsBatch directly without retries', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
                const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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

            it('should use individual updates when useBatchUpdates is false', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
                    dbWriteMode: 'NO_ASSERT',
                    useBatchUpdates: false,
                })

                await personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStore.flush()

                // Individual mode should call updatePerson, not updatePersonsBatch
                expect(mockRepo.updatePerson).toHaveBeenCalledTimes(1)
                expect(mockRepo.updatePersonsBatch).not.toHaveBeenCalled()
                expect(mockRepo.updatePersonAssertVersion).not.toHaveBeenCalled()
            })

            it('should retry individual updates on error when useBatchUpdates is false', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
                    dbWriteMode: 'NO_ASSERT',
                    useBatchUpdates: false,
                    maxOptimisticUpdateRetries: 2,
                    optimisticUpdateRetryInterval: 1,
                })

                // Mock updatePerson to fail twice then succeed
                let callCount = 0
                mockRepo.updatePerson = jest.fn().mockImplementation(() => {
                    callCount++
                    if (callCount <= 2) {
                        return Promise.reject(new Error('Temporary error'))
                    }
                    return Promise.resolve([person, []])
                })

                await personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    { new_value: 'new_value' },
                    [],
                    {},
                    'test'
                )
                await personStore.flush()

                // Should have retried
                expect(mockRepo.updatePerson).toHaveBeenCalledTimes(3)
                expect(mockRepo.updatePersonsBatch).not.toHaveBeenCalled()
            })
        })

        describe('flush with ASSERT_VERSION mode', () => {
            it('should call updatePersonAssertVersion with retries', async () => {
                const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
                const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
                const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
                expect(emitIngestionWarning).toHaveBeenCalledWith(mockIngestionWarningsOutputs, teamId, {
                    type: 'person_upsert_message_size_too_large',
                    details: {
                        personId: person.uuid,
                        distinctId: 'test',
                    },
                    category: 'size',
                    severity: 'error',
                    pipelineStep: 'person-store',
                })
                expect(mockRepo.updatePerson).not.toHaveBeenCalled() // No fallback for MessageSizeTooLarge
            })
        })

        describe('concurrent updates with different dbWriteModes', () => {
            it('should handle multiple updates with different modes correctly', async () => {
                const noAssertMockRepo = createMockRepository()
                const assertVersionMockRepo = createMockRepository()

                const noAssertStore = new BatchWritingPersonsStore(noAssertMockRepo, mockIngestionWarningsOutputs, {
                    dbWriteMode: 'NO_ASSERT',
                })
                const assertVersionStore = new BatchWritingPersonsStore(
                    assertVersionMockRepo,
                    mockIngestionWarningsOutputs,
                    {
                        dbWriteMode: 'ASSERT_VERSION',
                    }
                )

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
        const assertVersionStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs, {
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
        const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
        const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
        const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx, 0)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx, 0)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx, 0)

            // Verify the repository method was called
            expect(tx.moveDistinctIds).toHaveBeenCalledTimes(1)
            expect(tx.moveDistinctIds).toHaveBeenCalledWith(sourcePerson, targetPerson, undefined)

            // Verify source cache is cleared
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, sourcePerson.id)).toBeUndefined()
        })

        it('should handle complex merge scenario with multiple properties', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct', undefined, tx, 0)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const result = await personStore.addPersonlessDistinctId(teamId, 'test-distinct', 0)

            expect(mockRepo.addPersonlessDistinctId).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(true)
        })

        it('should handle repository returning false', async () => {
            const mockRepo = createMockRepository()
            mockRepo.addPersonlessDistinctId = jest.fn().mockResolvedValue(false)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const result = await personStore.addPersonlessDistinctId(teamId, 'test-distinct', 0)

            expect(mockRepo.addPersonlessDistinctId).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(false)
        })
    })

    describe('addPersonlessDistinctIdForMerge', () => {
        it('should call repository method and return result', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const result = await personStore.addPersonlessDistinctIdForMerge(teamId, 'test-distinct', undefined, 0)

            expect(mockRepo.addPersonlessDistinctIdForMerge).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(true)
        })

        it('should handle repository returning false', async () => {
            const mockRepo = createMockRepository()
            mockRepo.addPersonlessDistinctIdForMerge = jest.fn().mockResolvedValue(false)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const result = await personStore.addPersonlessDistinctIdForMerge(teamId, 'test-distinct', undefined, 0)

            expect(mockRepo.addPersonlessDistinctIdForMerge).toHaveBeenCalledWith(teamId, 'test-distinct')
            expect(result).toBe(false)
        })
    })

    describe('personPropertiesSize', () => {
        it('should call repository method and return result', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)
            const personId = 'test-person-id'
            const teamId = 1

            const result = await personStore.personPropertiesSize(personId, teamId)

            expect(mockRepo.personPropertiesSize).toHaveBeenCalledWith(personId, teamId)
            expect(result).toBe(1024)
        })

        it('should handle repository returning 0', async () => {
            const mockRepo = createMockRepository()
            mockRepo.personPropertiesSize = jest.fn().mockResolvedValue(0)
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)
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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

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

        it('should write to database when last_seen_at changes', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const personWithLastSeen = {
                ...person,
                last_seen_at: DateTime.fromISO('2024-01-01T10:00:00Z'),
            }

            // Update person with only last_seen_at change (via otherUpdates)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithLastSeen,
                {}, // no property changes
                [],
                { last_seen_at: DateTime.fromISO('2024-01-01T11:00:00Z') }, // new hour
                'test'
            )

            await personStore.flush()

            // Should write because last_seen_at changed
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
        })

        it('should NOT write to database when last_seen_at is unchanged', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const lastSeenTime = DateTime.fromISO('2024-01-01T10:00:00Z')
            const personWithLastSeen = {
                ...person,
                last_seen_at: lastSeenTime,
            }

            // Update person with same last_seen_at (no actual change)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithLastSeen,
                {}, // no property changes
                [],
                { last_seen_at: lastSeenTime }, // same timestamp - should not trigger change
                'test'
            )

            await personStore.flush()

            // Should NOT write because nothing changed
            expect(mockRepo.updatePersonsBatch).not.toHaveBeenCalled()
            expect(mockRepo.updatePerson).not.toHaveBeenCalled()
        })

        it('should take the newer last_seen_at when multiple updates occur', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const personWithLastSeen = {
                ...person,
                last_seen_at: DateTime.fromISO('2024-01-01T10:00:00Z'),
            }

            // First update with a newer timestamp
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithLastSeen,
                {},
                [],
                { last_seen_at: DateTime.fromISO('2024-01-01T12:00:00Z') },
                'test'
            )

            // Second update with an older timestamp (should be ignored)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithLastSeen,
                {},
                [],
                { last_seen_at: DateTime.fromISO('2024-01-01T11:00:00Z') },
                'test'
            )

            await personStore.flush()

            // Should write with the newer timestamp
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith([
                expect.objectContaining({
                    last_seen_at: DateTime.fromISO('2024-01-01T12:00:00Z'),
                }),
            ])
        })

        it('should write to database when last_seen_at changes from null', async () => {
            const mockRepo = createMockRepository()
            const personStore = new BatchWritingPersonsStore(mockRepo, mockIngestionWarningsOutputs)

            const personWithNoLastSeen = {
                ...person,
                last_seen_at: null,
            }

            // Update person setting last_seen_at for the first time
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                personWithNoLastSeen,
                {},
                [],
                { last_seen_at: DateTime.fromISO('2024-01-01T10:00:00Z') },
                'test'
            )

            await personStore.flush()

            // Should write because last_seen_at changed from null
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            expect(mockPersonProfileBatchUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
        })
    })

    describe('persistent cache (concurrentBatches > 1)', () => {
        it('cache data persists across batch boundaries (no reset)', async () => {
            const personStore = getPersonsStore()

            // Populate caches by fetching and updating a person
            await personStore.fetchForUpdate(teamId, 'distinct-1', 0)
            await personStore.fetchForChecking(teamId, 'distinct-2', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { name: 'test' }, [], {}, 'distinct-1')

            const updateCacheSizeBefore = personStore.getUpdateCache().size
            const checkCacheSizeBefore = personStore.getCheckCache().size
            expect(updateCacheSizeBefore).toBeGreaterThan(0)
            expect(checkCacheSizeBefore).toBeGreaterThan(0)

            // No reset() method; caches persist for the worker's lifetime.
            // Flushing writes dirty entries but does not evict.
            await personStore.flush()

            expect(personStore.getUpdateCache().size).toBe(updateCacheSizeBefore)
            expect(personStore.getCheckCache().size).toBe(checkCacheSizeBefore)
        })

        it('subsequent flushes pick up only newly-dirtied entries', async () => {
            const personStore = getPersonsStore()

            // First batch: populate and flush
            await personStore.fetchForUpdate(teamId, 'distinct-1', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { batch: '1' }, [], {}, 'distinct-1')
            await personStore.flush()

            // Second batch: same persistent cache, new write to a different distinct_id
            const person2 = { ...person, id: '2', properties: { original: 'value' } }
            mockRepo.fetchPerson.mockResolvedValueOnce(person2)

            await personStore.fetchForUpdate(teamId, 'distinct-2', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person2, { batch: '2' }, [], {}, 'distinct-2')
            await personStore.flush()

            // Two flushes, second one wrote the round 2 delta
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(2)
            expect(mockRepo.updatePersonsBatch).toHaveBeenLastCalledWith([
                expect.objectContaining({
                    properties_to_set: expect.objectContaining({ batch: '2' }),
                }),
            ])
        })

        it('reuses cached person data across batches (persistent-cache model)', async () => {
            const personStore = getPersonsStore()

            // First batch: cache person with specific properties
            const personBatch1 = { ...person, properties: { name: 'Batch1Person' } }
            mockRepo.fetchPerson.mockResolvedValueOnce(personBatch1)

            await personStore.fetchForUpdate(teamId, 'user-1', 0)
            await personStore.flush()

            // Second batch: same distinct_id should hit the persisted cache and
            // NOT re-fetch from DB. This is the cross-batch caching benefit
            // unlocked by the persistent-cache model.
            const fetchedPerson = await personStore.fetchForUpdate(teamId, 'user-1', 0)

            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1)
            expect(fetchedPerson?.properties).toEqual({ name: 'Batch1Person' })
        })

        it('clears needs_write on dirty entries synchronously during flush', async () => {
            // Linearization point: flush() must clear needs_write BEFORE awaiting
            // any DB I/O. Any code path that introduces an await between the
            // dirty-filter pass and the clear would re-open the cross-batch race
            // documented in the design doc — this test guards against that.
            const personStore = getPersonsStore()

            await personStore.fetchForUpdate(teamId, 'distinct-1', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { name: 'test' }, [], {}, 'distinct-1')

            const updateCache = personStore.getUpdateCache()
            const dirtyEntriesBefore = Array.from(updateCache.values()).filter((u) => u?.needs_write)
            expect(dirtyEntriesBefore.length).toBeGreaterThan(0)

            // Kick off flush WITHOUT awaiting it, then synchronously inspect
            // needs_write. If flush yields before clearing the bit, this will
            // catch it — the assertion runs at the first microtask boundary.
            const flushPromise = personStore.flush()

            const stillDirty = Array.from(updateCache.values()).filter((u) => u?.needs_write)
            expect(stillDirty).toHaveLength(0)

            await flushPromise
        })

        it('persists update cache across flushes; re-dirty drives the next flush', async () => {
            // The persistent-cache model: flushing does NOT remove entries from
            // personUpdateCache. A subsequent write to the same distinct_id
            // re-dirties the existing entry, and the next flush picks up the
            // delta.
            const personStore = getPersonsStore()

            await personStore.fetchForUpdate(teamId, 'distinct-1', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { round: '1' }, [], {}, 'distinct-1')

            const updateCacheKeyBefore = Array.from(personStore.getUpdateCache().keys())
            expect(updateCacheKeyBefore.length).toBeGreaterThan(0)

            await personStore.flush()

            // Cache entries persist
            expect(Array.from(personStore.getUpdateCache().keys())).toEqual(updateCacheKeyBefore)
            // All entries are clean after flush
            for (const entry of personStore.getUpdateCache().values()) {
                if (entry) {
                    expect(entry.needs_write).toBe(false)
                }
            }

            // Re-dirty via a second update
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { round: '2' }, [], {}, 'distinct-1')
            const dirtyAfterSecondWrite = Array.from(personStore.getUpdateCache().values()).filter(
                (u) => u?.needs_write
            )
            expect(dirtyAfterSecondWrite.length).toBeGreaterThan(0)

            mockRepo.updatePersonsBatch.mockClear()
            await personStore.flush()

            // Second flush wrote the round 2 delta
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledWith([
                expect.objectContaining({
                    properties_to_set: expect.objectContaining({ round: '2' }),
                }),
            ])
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
                [{ distinctId: 'extra-id-1' }, { distinctId: 'extra-id-2' }, { distinctId: 'extra-id-3' }],
                undefined,
                0
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
                { teamId, distinctId: 'user-1', batchId: 0 },
                { teamId, distinctId: 'user-2', batchId: 0 },
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
                { teamId, distinctId: 'user-1', batchId: 0 },
                { teamId, distinctId: 'user-2', batchId: 0 },
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
                { teamId, distinctId: 'user-1', batchId: 0 },
                { teamId, distinctId: 'user-2', batchId: 0 },
            ])

            // Should only fetch user-2 since user-1 was already cached
            expect(mockRepo.fetchPersonsByDistinctIds).toHaveBeenCalledWith([{ teamId, distinctId: 'user-2' }], false)
        })

        it('should skip entries already in update cache', async () => {
            const personStoreForBatch = getPersonsStore()

            // Pre-populate by fetching for update
            mockRepo.fetchPerson.mockResolvedValueOnce(person)
            await personStoreForBatch.fetchForUpdate(teamId, 'user-1', 0)

            const person2 = { ...person, id: '2', team_id: teamId, distinct_id: 'user-2' }
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([person2])

            await personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1', batchId: 0 },
                { teamId, distinctId: 'user-2', batchId: 0 },
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
                { teamId, distinctId: 'user-1', batchId: 0 },
                { teamId, distinctId: 'user-2', batchId: 0 },
            ])

            expect(mockRepo.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('should allow fetchForChecking to use prefetched data', async () => {
            const personStoreForBatch = getPersonsStore()

            const prefetchedPerson = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([prefetchedPerson])

            await personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1', batchId: 0 }])

            // Now fetchForChecking should use cached data
            const result = await personStoreForBatch.fetchForChecking(teamId, 'user-1', 0)

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

            await personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1', batchId: 0 }])

            // Now fetchForUpdate should use cached data
            const result = await personStoreForBatch.fetchForUpdate(teamId, 'user-1', 0)

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
            const prefetchCompletion = personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1', batchId: 0 },
            ])

            // Now call fetchForChecking while prefetch is still in flight
            const fetchCheckingPromise = personStoreForBatch.fetchForChecking(teamId, 'user-1', 0)

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
            const prefetchCompletion = personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1', batchId: 0 },
            ])

            // Now call fetchForUpdate while prefetch is still in flight
            const fetchUpdatePromise = personStoreForBatch.fetchForUpdate(teamId, 'user-1', 0)

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

        it('should discard late prefetch writes after the batch is released', async () => {
            const personStoreForBatch = getPersonsStore()

            const prefetchedPerson = { ...person, id: '1', team_id: teamId, distinct_id: 'user-1' }

            let resolvePrefetch: (value: (typeof prefetchedPerson)[]) => void
            const prefetchPromise = new Promise<(typeof prefetchedPerson)[]>((resolve) => {
                resolvePrefetch = resolve
            })
            mockRepo.fetchPersonsByDistinctIds.mockReturnValueOnce(prefetchPromise)

            const prefetchCompletion = personStoreForBatch.prefetchPersons([
                { teamId, distinctId: 'user-1', batchId: 0 },
            ])

            personStoreForBatch.releaseBatch(0)

            resolvePrefetch!([prefetchedPerson])
            await prefetchCompletion

            expect(personStoreForBatch.getCheckCache().has(`${teamId}:user-1`)).toBe(false)
            expect(personStoreForBatch.getUpdateCache().has(`${teamId}:1`)).toBe(false)

            const batchDistinctKeys = (personStoreForBatch as any)['batchDistinctKeys'] as Map<number, Set<string>>
            expect(batchDistinctKeys.has(0)).toBe(false)
            const distinctKeyRefCount = (personStoreForBatch as any)['distinctKeyRefCount'] as Map<string, number>
            expect(distinctKeyRefCount.has(`${teamId}:user-1`)).toBe(false)
        })

        it('should resolve (not reject) on a transient persons-Postgres failure', async () => {
            const personStoreForBatch = getPersonsStore()

            mockRepo.fetchPersonsByDistinctIds.mockRejectedValueOnce(
                new DependencyUnavailableError('connect ECONNREFUSED', 'Postgres', new Error('connect ECONNREFUSED'))
            )

            // Prefetch is fired without being awaited by its pipeline step, so a rejection here would
            // surface as an unhandled rejection and crash the worker. It must resolve instead.
            await expect(
                personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1', batchId: 0 }])
            ).resolves.toBeUndefined()

            // Nothing should have been cached for the failed entry
            expect(personStoreForBatch.getCheckCache().has(`${teamId}:user-1`)).toBe(false)
        })

        it('should rethrow an unexpected batch fetch failure rather than mask it', async () => {
            const personStoreForBatch = getPersonsStore()

            // A non-transient error (e.g. a broken query) must surface loudly, not be swallowed.
            mockRepo.fetchPersonsByDistinctIds.mockRejectedValueOnce(new Error('something unexpected'))

            await expect(
                personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1', batchId: 0 }])
            ).rejects.toThrow('something unexpected')
        })

        it('should let fetchForUpdate fall back to an on-demand fetch after a failed prefetch', async () => {
            const personStoreForBatch = getPersonsStore()

            mockRepo.fetchPersonsByDistinctIds.mockRejectedValueOnce(
                new DependencyUnavailableError('connect ECONNREFUSED', 'Postgres', new Error('connect ECONNREFUSED'))
            )

            await personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1', batchId: 0 }])

            // The failed prefetch left the caches empty, so fetchForUpdate must do its own fetch.
            const result = await personStoreForBatch.fetchForUpdate(teamId, 'user-1', 0)

            expect(result).toEqual(person)
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1)
        })

        it('should propagate a transient in-flight failure to fetchForChecking, not report the person absent', async () => {
            const personStoreForBatch = getPersonsStore()

            // Control when the batch fetch settles so fetchForChecking piggybacks on the in-flight prefetch.
            let rejectFetch: (reason: Error) => void
            const fetchPromise = new Promise<InternalPerson[]>((_resolve, reject) => {
                rejectFetch = reject
            })
            mockRepo.fetchPersonsByDistinctIds.mockReturnValueOnce(fetchPromise)

            const prefetch = personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1', batchId: 0 }])
            const checking = personStoreForBatch.fetchForChecking(teamId, 'user-1', 0)

            rejectFetch!(new DependencyUnavailableError('connect ECONNREFUSED', 'Postgres', new Error('boom')))

            // Must reject so the per-distinct-id pipeline retries — not resolve null ("person absent"),
            // which would make processPersonlessStep create a fake person for an event that has a real one.
            await expect(checking).rejects.toThrow('connect ECONNREFUSED')
            // The fire-and-forget prefetch itself still recovers so it can't crash the worker.
            await expect(prefetch).resolves.toBeUndefined()
        })

        it('should propagate a transient in-flight failure to fetchForUpdate rather than silently refetch', async () => {
            const personStoreForBatch = getPersonsStore()

            let rejectFetch: (reason: Error) => void
            const fetchPromise = new Promise<InternalPerson[]>((_resolve, reject) => {
                rejectFetch = reject
            })
            mockRepo.fetchPersonsByDistinctIds.mockReturnValueOnce(fetchPromise)

            const prefetch = personStoreForBatch.prefetchPersons([{ teamId, distinctId: 'user-1', batchId: 0 }])
            const update = personStoreForBatch.fetchForUpdate(teamId, 'user-1', 0)

            rejectFetch!(new DependencyUnavailableError('connect ECONNREFUSED', 'Postgres', new Error('boom')))

            await expect(update).rejects.toThrow('connect ECONNREFUSED')
            await expect(prefetch).resolves.toBeUndefined()
        })
    })

    describe('cross-batch cache scenarios (persistent-cache model)', () => {
        // These tests simulate the pipeline calling flush() at the end of each
        // "batch" while the store's caches persist. They verify that the data
        // we care about — accumulated person updates, distinct_id→person_id
        // mappings, merge results — survive across flush() boundaries and are
        // correctly merged into the next batch's writes.

        it('accumulates property updates for the same person across two batches', async () => {
            const personStore = getPersonsStore()

            // BATCH 1 — set props {a, b} on distinct_id_1's person
            await personStore.fetchForUpdate(teamId, 'distinct_id_1', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                person,
                { a: '1', b: '2' },
                [],
                {},
                'distinct_id_1'
            )
            await personStore.flush()

            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1)
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            expect(mockRepo.updatePersonsBatch).toHaveBeenLastCalledWith([
                expect.objectContaining({
                    properties_to_set: expect.objectContaining({ a: '1', b: '2' }),
                }),
            ])

            // BATCH 2 — add prop {c}, unset {a}. Cache for distinct_id_1 should
            // already have the merged state from batch 1 (no re-fetch).
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { c: '3' }, ['a'], {}, 'distinct_id_1')
            await personStore.flush()

            // No second fetch — persistent cache had the person
            expect(mockRepo.fetchPerson).toHaveBeenCalledTimes(1)
            // Second flush writes the accumulated state — which includes the
            // batch 1 changes still in the cache (`a`, `b`) merged with batch
            // 2 changes (`c` added, `a` unset).
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(2)
            const secondCallPayload = mockRepo.updatePersonsBatch.mock.calls[1][0][0]
            expect(secondCallPayload.properties_to_set).toEqual(expect.objectContaining({ b: '2', c: '3' }))
            expect(secondCallPayload.properties_to_unset).toContain('a')
        })

        it('two distinct_ids pointing to the same person share a single cache entry across batches', async () => {
            const personStore = getPersonsStore()

            // Both fetches resolve to the SAME underlying person (same uuid / id).
            // Simulates the case where distinct_id_a and distinct_id_b have
            // already been merged to one person in the DB.
            mockRepo.fetchPerson.mockResolvedValue(person)

            // BATCH 1 — write via distinct_id_a
            await personStore.fetchForUpdate(teamId, 'distinct_id_a', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { via: 'a' }, [], {}, 'distinct_id_a')
            await personStore.flush()

            // BATCH 2 — write via distinct_id_b. The store maintains a per-
            // distinct_id update cache, so this hits a separate cache slot,
            // but both slots map to the same person id internally (via
            // distinctIdToPersonId resolution).
            await personStore.fetchForUpdate(teamId, 'distinct_id_b', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { via: 'b' }, [], {}, 'distinct_id_b')
            await personStore.flush()

            // Both batches landed updates targeting the same person.uuid.
            const allUpdatePayloads = mockRepo.updatePersonsBatch.mock.calls.flatMap((call: any) => call[0])
            expect(allUpdatePayloads).toHaveLength(2)
            for (const payload of allUpdatePayloads) {
                expect(payload.uuid).toBe(person.uuid)
            }
        })

        it('does not double-write a stale entry when the same person is touched in batch A, untouched in batch B', async () => {
            const personStore = getPersonsStore()

            // BATCH 1 — write
            await personStore.fetchForUpdate(teamId, 'distinct_id_1', 0)
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                person,
                { name: 'first' },
                [],
                {},
                'distinct_id_1'
            )
            await personStore.flush()
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)

            // BATCH 2 — no writes. Just reads from the cache.
            const cachedPerson = await personStore.fetchForUpdate(teamId, 'distinct_id_1', 0)
            expect(cachedPerson).toBeTruthy()
            await personStore.flush()

            // Batch 2 must NOT have triggered another DB write — needs_write
            // was cleared by the first flush and no mutation re-dirtied it.
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
        })

        it('preserves distinctId→personId mapping after addDistinctId across batches', async () => {
            const personStore = getPersonsStore()
            mockRepo.fetchPerson.mockResolvedValue(person)

            // BATCH 1 — primary distinct_id fetched, then a new distinct_id
            // is added to the same person.
            await personStore.fetchForUpdate(teamId, 'distinct_id_primary', 0)
            await personStore.addDistinctId(person, 'distinct_id_secondary', 0, undefined, 0)
            await personStore.flush()

            const distinctIdToPersonId = (personStore as any).distinctIdToPersonId as Map<string, string>
            const secondaryMappingAfterBatch1 = distinctIdToPersonId.get(`${teamId}:distinct_id_secondary`)
            expect(secondaryMappingAfterBatch1).toBe(person.id)

            // BATCH 2 — write via the newly-added distinct_id. It should
            // resolve to the same person via the persistent mapping; no
            // additional fetchPerson roundtrip.
            mockRepo.fetchPerson.mockClear()
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                person,
                { from: 'secondary' },
                [],
                {},
                'distinct_id_secondary'
            )
            await personStore.flush()

            // The mapping is preserved
            expect(distinctIdToPersonId.get(`${teamId}:distinct_id_secondary`)).toBe(person.id)
            // ...and we didn't re-fetch the person for the secondary distinct_id
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
        })

        it('moveDistinctIds in batch A makes batch B writes target the merged person', async () => {
            const personStore = getPersonsStore()

            const sourcePerson: InternalPerson = {
                ...person,
                id: 'source-id',
                uuid: 'source-uuid',
                properties: { source: 'true' },
            }
            const targetPerson: InternalPerson = {
                ...person,
                id: 'target-id',
                uuid: 'target-uuid',
                properties: { target: 'true' },
            }

            // BATCH 1 — fetch both persons into the cache, then merge source
            // → target by moving the source's distinct_ids onto the target.
            mockRepo.fetchPerson.mockResolvedValueOnce(sourcePerson).mockResolvedValueOnce(targetPerson)

            await personStore.fetchForUpdate(teamId, 'distinct_id_source', 0)
            await personStore.fetchForUpdate(teamId, 'distinct_id_target', 0)

            const tx = createMockTransaction() as any
            tx.moveDistinctIds.mockResolvedValueOnce({
                success: true,
                messages: [],
                distinctIdsMoved: ['distinct_id_source'],
            })

            await personStore.moveDistinctIds(sourcePerson, targetPerson, 'distinct_id_target', undefined, tx, 0)
            await personStore.flush()

            // BATCH 2 — write via the previously-source distinct_id.
            // distinctIdToPersonId now maps it to the target.
            const distinctIdToPersonId = (personStore as any).distinctIdToPersonId as Map<string, string>
            expect(distinctIdToPersonId.get(`${teamId}:distinct_id_source`)).toBe(targetPerson.id)

            mockRepo.fetchPerson.mockClear()
            mockRepo.updatePersonsBatch.mockClear()
            await personStore.updatePersonWithPropertiesDiffForUpdate(
                targetPerson,
                { post_merge: 'yes' },
                [],
                {},
                'distinct_id_source'
            )
            await personStore.flush()

            // We should NOT have re-fetched (mapping cached) and the write
            // should be attributed to the target person, not the source.
            expect(mockRepo.fetchPerson).not.toHaveBeenCalled()
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)
            const payload = mockRepo.updatePersonsBatch.mock.calls[0][0][0]
            expect(payload.uuid).toBe(targetPerson.uuid)
            expect(payload.properties_to_set).toEqual(expect.objectContaining({ post_merge: 'yes' }))
        })
    })

    describe('shutdown()', () => {
        it('succeeds without calling flush when no dirty entries exist', async () => {
            const flushSpy = jest.spyOn(personStore, 'flush')

            await personStore.shutdown()

            expect(flushSpy).not.toHaveBeenCalled()
            expect(mockIngestionWarningsOutputs.produce).not.toHaveBeenCalled()
        })

        it('throws when dirty entries exist — caller must flush first', () => {
            const cache = (personStore as any).personUpdateCache as Map<string, any>
            cache.set(`${teamId}:${person.id}`, {
                ...fromInternalPerson(person, 'test'),
                needs_write: true,
                properties_to_set: { x: '1' },
            })

            expect(() => personStore.shutdown()).toThrow(/dirty cache entries/)

            cache.delete(`${teamId}:${person.id}`)
        })

        it('emits accumulated metrics before throwing on dirty cache', () => {
            const cache = (personStore as any).personUpdateCache as Map<string, any>
            cache.set(`${teamId}:${person.id}`, {
                ...fromInternalPerson(person, 'test'),
                needs_write: true,
                properties_to_set: { x: '1' },
            })

            const emitSpy = jest.spyOn(personStore as any, 'emitAccumulatedMetrics')

            expect(() => personStore.shutdown()).toThrow()

            expect(emitSpy).toHaveBeenCalledTimes(1)

            cache.delete(`${teamId}:${person.id}`)
        })

        it('flushAndProduceMessages drains dirty entries and produces Kafka messages', async () => {
            const cache = (personStore as any).personUpdateCache as Map<string, any>
            cache.set(`${teamId}:${person.id}`, {
                id: person.id,
                uuid: person.uuid,
                team_id: teamId,
                distinct_id: 'test',
                needs_write: true,
                properties: person.properties,
                properties_to_set: { new_prop: 'value' },
                properties_to_unset: [],
                version: person.version,
                created_at: person.created_at,
                is_identified: false,
                is_user_id: null,
            })

            const message = { output: PERSONS_OUTPUT, value: Buffer.from('{}') }
            const flushSpy = jest
                .spyOn(personStore, 'flush')
                .mockResolvedValue([{ messages: [message], teamId, distinctId: 'test', uuid: person.uuid }])

            await personStore.flushAndProduceMessages()

            expect(flushSpy).toHaveBeenCalledTimes(1)
            expect(mockIngestionWarningsOutputs.produce).toHaveBeenCalledTimes(1)
            expect(mockIngestionWarningsOutputs.produce).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: message.value,
                teamId,
            })

            // Remove injected entry so afterEach shutdown does not re-trigger a flush
            cache.delete(`${teamId}:${person.id}`)
        })
    })

    describe('releaseBatch', () => {
        it('is a no-op for an unknown batchId', () => {
            expect(() => personStore.releaseBatch(999)).not.toThrow()
        })

        it('reports dirty entries and referenced batches in flush stats', () => {
            const personUpdate = { ...fromInternalPerson(person, 'user-a'), needs_write: true }

            personStore.setCachedPersonForUpdate(teamId, 'user-a', personUpdate, 0)
            personStore.setCachedPersonForUpdate(teamId, 'user-a', { ...personUpdate }, 1)

            expect(personStore.getFlushStats()).toEqual({
                dirtyEntryCount: 1,
                referencedBatchCount: 2,
                cacheEntryCount: 1,
            })
        })

        it('evicts check cache and distinctId mapping after single batch is released', () => {
            personStore.setCheckCachedPerson(teamId, 'user-a', person, 0)
            personStore.setCachedPersonForUpdate(teamId, 'user-a', fromInternalPerson(person, 'user-a'), 0)

            expect(personStore.getCheckCache().has(`${teamId}:user-a`)).toBe(true)

            personStore.releaseBatch(0)

            expect(personStore.getCheckCache().has(`${teamId}:user-a`)).toBe(false)
            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'user-a')).toBeUndefined()
        })

        it('only evicts when the last referencing batch is released', () => {
            personStore.setCheckCachedPerson(teamId, 'user-a', person, 0)
            personStore.setCheckCachedPerson(teamId, 'user-a', person, 1)

            personStore.releaseBatch(0)
            // Still held by batch 1
            expect(personStore.getCheckCache().has(`${teamId}:user-a`)).toBe(true)

            personStore.releaseBatch(1)
            // Now unreferenced
            expect(personStore.getCheckCache().has(`${teamId}:user-a`)).toBe(false)
        })

        it('defers eviction of dirty person update entries until after flush', async () => {
            const personUpdate = { ...fromInternalPerson(person, 'user-a'), needs_write: true }
            personStore.setCachedPersonForUpdate(teamId, 'user-a', personUpdate, 0)

            personStore.releaseBatch(0)

            // Both the cache entry AND the distinctId mapping are kept alive while dirty —
            // evicting the mapping would orphan the cache entry after the next flush.
            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'user-a')).toBeDefined()
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, person.id)).toBeDefined()

            // After flush clears needs_write, processDeferredEvictions() runs and
            // cleans up both the cache entry and the mapping.
            await personStore.flush()

            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'user-a')).toBeUndefined()
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, person.id)).toBeUndefined()
        })

        it('deferred eviction is skipped if entry is re-dirtied during the DB write', async () => {
            // properties_to_set must be non-empty so getPersonUpdateOutcome returns 'changed'
            // and the entry is included in the batch (otherwise the mock is never called).
            const personUpdate = {
                ...fromInternalPerson(person, 'user-a'),
                needs_write: true,
                properties_to_set: { new_prop: 'new_value' },
            }
            personStore.setCachedPersonForUpdate(teamId, 'user-a', personUpdate, 0)
            personStore.releaseBatch(0)

            // Simulate a concurrent batch re-dirtying the entry during the async DB write
            // (i.e., after the linearization point clears needs_write but before processDeferredEvictions).
            // kafkaMessage must be truthy to avoid the fallback individual-update path.
            mockRepo.updatePersonsBatch.mockImplementationOnce((updates: any[]) => {
                const results = new Map()
                for (const update of updates) {
                    results.set(update.uuid, { success: true, version: update.version + 1, kafkaMessage: {} })
                }
                // getCachedPersonForUpdateByPersonId returns a deep copy, so we must access the
                // internal map directly to simulate a concurrent batch re-dirtying the entry.
                const cache: Map<string, any> = (personStore as any)['personUpdateCache']
                const actualUpdate = cache.get(`${teamId}:${person.id}`)
                if (actualUpdate) {
                    actualUpdate.needs_write = true
                }
                return Promise.resolve(results)
            })

            await personStore.flush()

            // Entry is still alive because it was re-dirtied during the DB write
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, person.id)).toBeDefined()

            // A second flush clears it properly
            await personStore.flush()
            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, person.id)).toBeUndefined()
            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'user-a')).toBeUndefined()
        })

        it('evicts clean person update entries from personUpdateCache', () => {
            const personUpdate = { ...fromInternalPerson(person, 'user-a'), needs_write: false }
            personStore.setCachedPersonForUpdate(teamId, 'user-a', personUpdate, 0)

            personStore.releaseBatch(0)

            expect(personStore.getCachedPersonForUpdateByPersonId(teamId, person.id)).toBeUndefined()
        })

        it('clears personlessBatchResults for evicted distinct IDs', () => {
            personStore.setCheckCachedPerson(teamId, 'user-a', null, 0)
            ;(personStore as any)['personlessBatchResults'].set(`${teamId}:user-a`, true)

            personStore.releaseBatch(0)

            expect(personStore.getPersonlessBatchResult(teamId, 'user-a')).toBeUndefined()
        })

        it('evicts personlessBatchResults written via addPersonlessDistinctIdForMerge after batch release', async () => {
            const batchStore = new BatchBoundPersonsStore(personStore, 0)

            await batchStore.addPersonlessDistinctIdForMerge(teamId, 'lonely-merge-distinct')
            expect(personStore.getPersonlessBatchResult(teamId, 'lonely-merge-distinct')).toBe(true)

            personStore.releaseBatch(0)

            expect(personStore.getPersonlessBatchResult(teamId, 'lonely-merge-distinct')).toBeUndefined()
        })

        it('tracks property-update cache writes through the batch-bound store', async () => {
            const batchStore = new BatchBoundPersonsStore(personStore, 0)

            await batchStore.updatePersonWithPropertiesDiffForUpdate(
                person,
                { plan: 'enterprise' },
                [],
                {},
                'batch-bound-property'
            )

            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'batch-bound-property')).toBeDefined()

            await personStore.flush()
            personStore.releaseBatch(0)

            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'batch-bound-property')).toBeUndefined()
        })

        it('tracks merge-update cache writes through the batch-bound store', async () => {
            const batchStore = new BatchBoundPersonsStore(personStore, 0)

            await batchStore.updatePersonForMerge(
                person,
                { properties: { merge_marker: 'tracked' } },
                'batch-bound-merge'
            )

            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'batch-bound-merge')).toBeDefined()

            await personStore.flush()
            personStore.releaseBatch(0)

            expect(personStore.getCachedPersonForUpdateByDistinctId(teamId, 'batch-bound-merge')).toBeUndefined()
        })

        it('only evicts entries for the released batch, leaving other batch entries intact', () => {
            personStore.setCheckCachedPerson(teamId, 'user-a', person, 0)
            personStore.setCheckCachedPerson(teamId, 'user-b', person, 1)

            personStore.releaseBatch(0)

            expect(personStore.getCheckCache().has(`${teamId}:user-a`)).toBe(false)
            expect(personStore.getCheckCache().has(`${teamId}:user-b`)).toBe(true)
        })

        it('cleans up batch tracking data after release', () => {
            personStore.setCheckCachedPerson(teamId, 'user-a', person, 0)

            personStore.releaseBatch(0)

            const batchDistinctKeys = (personStore as any)['batchDistinctKeys'] as Map<number, Set<string>>
            expect(batchDistinctKeys.has(0)).toBe(false)
            const distinctKeyRefCount = (personStore as any)['distinctKeyRefCount'] as Map<string, number>
            expect(distinctKeyRefCount.has(`${teamId}:user-a`)).toBe(false)
        })

        it('overlapping prefetches keep entry alive through first flush, evict on second', async () => {
            // Simulate batch 0 and batch 1 both prefetching the same distinct ID
            // before either has flushed (the concurrent-batches scenario).
            mockRepo.fetchPersonsByDistinctIds.mockResolvedValueOnce([{ ...person, distinct_id: 'user-a' }])
            await personStore.prefetchPersons([{ teamId, distinctId: 'user-a', batchId: 0 }])
            // Batch 1 prefetches same user — already in cache, just bumps refcount
            await personStore.prefetchPersons([{ teamId, distinctId: 'user-a', batchId: 1 }])

            const distinctKeyRefCount = (personStore as any)['distinctKeyRefCount'] as Map<string, number>
            expect(distinctKeyRefCount.get(`${teamId}:user-a`)).toBe(2)

            // Batch 0 per-event work: update user-a
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { prop0: 'batch0' }, [], {}, 'user-a', 0)

            // Batch 0 flushes — writes the dirty entry, clears needs_write
            await personStore.flush()
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(1)

            // Release batch 0 — refcount drops to 1, entry survives for batch 1
            personStore.releaseBatch(0)
            expect(distinctKeyRefCount.get(`${teamId}:user-a`)).toBe(1)
            expect(personStore.getCheckCache().has(`${teamId}:user-a`)).toBe(true)

            // Batch 1 per-event work: update user-a (reuses the cached entry, no DB re-fetch)
            await personStore.updatePersonWithPropertiesDiffForUpdate(person, { prop1: 'batch1' }, [], {}, 'user-a', 1)

            // Batch 1 flushes — writes batch 1's dirty entry
            await personStore.flush()
            expect(mockRepo.updatePersonsBatch).toHaveBeenCalledTimes(2)

            // Release batch 1 — refcount drops to 0, entry evicted
            personStore.releaseBatch(1)
            expect(distinctKeyRefCount.has(`${teamId}:user-a`)).toBe(false)
            expect(personStore.getCheckCache().has(`${teamId}:user-a`)).toBe(false)
        })
    })
})
