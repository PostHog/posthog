import { DateTime } from 'luxon'

import { Hub, InternalPerson, PersonBatchWritingMode, TeamId } from '~/types'
import { DB } from '~/utils/db/db'
import { UUID7 } from '~/utils/utils'

import { BatchWritingPersonsStore, BatchWritingPersonsStoreForBatch } from './batch-writing-person-store'
import { MeasuringPersonsStore, MeasuringPersonsStoreForBatch } from './measuring-person-store'
import { PersonStoreManager, PersonStoreManagerForBatch } from './person-store-manager'
import { fromInternalPerson } from './person-update-batch'

describe('PersonStoreManager', () => {
    let hub: Hub
    let db: DB
    let measuringStore: MeasuringPersonsStore
    let batchStore: BatchWritingPersonsStore
    let manager: PersonStoreManager
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
        let latestPerson = person
        db = {
            postgres: {
                transaction: jest.fn().mockImplementation(async (_usage, _tag, transaction) => {
                    return await transaction(transaction)
                }),
            },
            fetchPerson: jest.fn().mockImplementation(() => {
                return Promise.resolve(latestPerson)
            }),
            createPerson: jest
                .fn()
                .mockImplementation(
                    (
                        _createdAt,
                        properties,
                        _propertiesLastUpdatedAt,
                        _propertiesLastOperation,
                        _teamId,
                        _isUserId,
                        _isIdentified,
                        id,
                        _distinctIds
                    ) => {
                        dbCounter++
                        latestPerson = {
                            ...latestPerson,
                            version: dbCounter,
                            id: latestPerson.id || id,
                            properties: latestPerson.properties || properties,
                        }
                        return Promise.resolve([latestPerson, []])
                    }
                ),
            updatePerson: jest.fn().mockImplementation((personInput, update) => {
                dbCounter++
                latestPerson = {
                    ...personInput,
                    properties: { ...personInput.properties, ...update.properties },
                    version: dbCounter,
                }
                return Promise.resolve([latestPerson, [], false]) // no version disparity
            }),
            updatePersonAssertVersion: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            deletePerson: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
            moveDistinctIds: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
            addDistinctId: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
        } as unknown as DB

        hub = {
            PERSON_BATCH_WRITING_MODE: 'NONE' as PersonBatchWritingMode,
        } as Hub

        measuringStore = new MeasuringPersonsStore(db, {
            personCacheEnabledForUpdates: true,
            personCacheEnabledForChecks: true,
        })
        batchStore = new BatchWritingPersonsStore(db)
        manager = new PersonStoreManager(hub, measuringStore, batchStore)
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('forBatch', () => {
        it('should return measuring store forBatch by default', () => {
            hub.PERSON_BATCH_WRITING_MODE = 'NONE'
            manager = new PersonStoreManager(hub, measuringStore, batchStore)

            const batchStoreForBatch = manager.forBatch()
            // Check that it returns the correct type, not the exact same instance
            expect(batchStoreForBatch).toBeInstanceOf(Object)
            expect(batchStoreForBatch.constructor.name).toBe('MeasuringPersonsStoreForBatch')
        })

        it('should return batch store forBatch when mode is BATCH', () => {
            hub.PERSON_BATCH_WRITING_MODE = 'BATCH'
            manager = new PersonStoreManager(hub, measuringStore, batchStore)

            const batchStoreForBatch = manager.forBatch()
            // Check that it returns the correct type, not the exact same instance
            expect(batchStoreForBatch).toBeInstanceOf(Object)
            expect(batchStoreForBatch.constructor.name).toBe('BatchWritingPersonsStoreForBatch')
        })

        it('should return PersonStoreManagerForBatch when mode is SHADOW and within shadow mode percentage', () => {
            hub.PERSON_BATCH_WRITING_MODE = 'SHADOW'
            hub.PERSON_BATCH_WRITING_SHADOW_MODE_PERCENTAGE = 100
            manager = new PersonStoreManager(hub, measuringStore, batchStore)

            const shadowStore = manager.forBatch()
            expect(shadowStore).toBeInstanceOf(PersonStoreManagerForBatch)
        })

        it('should return MeasuringPersonsStoreForBatch when mode is SHADOW and outside shadow mode percentage', () => {
            hub.PERSON_BATCH_WRITING_MODE = 'SHADOW'
            hub.PERSON_BATCH_WRITING_SHADOW_MODE_PERCENTAGE = 0
            manager = new PersonStoreManager(hub, measuringStore, batchStore)

            const shadowStore = manager.forBatch()
            expect(shadowStore).toBeInstanceOf(MeasuringPersonsStoreForBatch)
        })
    })
})

describe('PersonStoreManagerForBatch (Shadow Mode)', () => {
    let db: DB
    let measuringStoreForBatch: MeasuringPersonsStoreForBatch
    let batchStoreForBatch: BatchWritingPersonsStoreForBatch
    let shadowManager: PersonStoreManagerForBatch
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
        let latestPerson = person
        db = {
            postgres: {
                transaction: jest.fn().mockImplementation(async (_usage, _tag, transaction) => {
                    return await transaction(transaction)
                }),
            },
            fetchPerson: jest.fn().mockImplementation(() => {
                return Promise.resolve(latestPerson)
            }),
            createPerson: jest
                .fn()
                .mockImplementation(
                    (
                        _createdAt,
                        properties,
                        _propertiesLastUpdatedAt,
                        _propertiesLastOperation,
                        _teamId,
                        _isUserId,
                        _isIdentified,
                        id,
                        _distinctIds
                    ) => {
                        dbCounter++
                        latestPerson = {
                            ...latestPerson,
                            version: dbCounter,
                            id: id || latestPerson.id,
                            properties: properties || latestPerson.properties,
                        }
                        return Promise.resolve([latestPerson, []])
                    }
                ),
            updatePerson: jest.fn().mockImplementation((personInput, update) => {
                dbCounter++
                const updatedPerson = {
                    ...personInput,
                    properties: { ...personInput.properties, ...(update.properties || {}) },
                    version: dbCounter,
                }
                return Promise.resolve([updatedPerson, [], false]) // no version disparity
            }),
            updatePersonAssertVersion: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            deletePerson: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
            moveDistinctIds: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
            addDistinctId: jest.fn().mockImplementation(() => {
                return Promise.resolve([])
            }),
        } as unknown as DB

        const measuringStore = new MeasuringPersonsStore(db, {
            personCacheEnabledForUpdates: true,
            personCacheEnabledForChecks: true,
        })
        const batchStore = new BatchWritingPersonsStore(db)
        measuringStoreForBatch = measuringStore.forBatch() as MeasuringPersonsStoreForBatch
        batchStoreForBatch = batchStore.forBatch() as BatchWritingPersonsStoreForBatch
        shadowManager = new PersonStoreManagerForBatch(measuringStoreForBatch, batchStoreForBatch)
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('fetchForChecking', () => {
        it('should call measuring store and set batch store cache', async () => {
            const result = await shadowManager.fetchForChecking(teamId, 'test-distinct')
            expect(result).toEqual(person)

            await shadowManager.flush()
            expect(db.fetchPerson).toHaveBeenCalledWith(teamId, 'test-distinct', { useReadReplica: true })
            expect(db.fetchPerson).toHaveBeenCalledTimes(1)

            // Check that batch store cache was set
            const checkCache = batchStoreForBatch.getCheckCache()
            expect(checkCache.get('1:test-distinct')).toEqual(person)
        })
    })

    describe('fetchForUpdate', () => {
        it('should call measuring store and set batch store cache if not cached', async () => {
            const result = await shadowManager.fetchForUpdate(teamId, 'test-distinct')
            expect(result).toEqual(person)

            await shadowManager.flush()
            expect(db.fetchPerson).toHaveBeenCalledWith(teamId, 'test-distinct', { useReadReplica: false })
            expect(db.fetchPerson).toHaveBeenCalledTimes(1)

            // Check that batch store update cache was set
            const updateCache = batchStoreForBatch.getUpdateCache()
            const cachedUpdate = updateCache.get(`${teamId}:${person.id}`)
            expect(cachedUpdate).toBeDefined()
            expect(cachedUpdate!.distinct_id).toBe('test-distinct')
        })

        it('should overwrite existing cache in batch store, but keep changeset', async () => {
            // Pre-populate batch store cache
            const existingUpdate = fromInternalPerson(person, 'test-distinct')
            existingUpdate.properties_to_set = { pre_existing: 'value' }
            batchStoreForBatch.setCachedPersonForUpdate(teamId, 'test-distinct', existingUpdate)

            const result = await shadowManager.fetchForUpdate(teamId, 'test-distinct')
            expect(result).toEqual(person)

            await shadowManager.flush()
            expect(db.fetchPerson).toHaveBeenCalledTimes(1)

            // Cache should override properties, but keep changeset
            const updateCache = batchStoreForBatch.getUpdateCache()
            const cachedUpdate = updateCache.get(`${teamId}:${person.id}`)
            expect(cachedUpdate!.properties).toEqual(person.properties)
            expect(cachedUpdate!.properties_to_set).toEqual(existingUpdate.properties_to_set)
        })
    })

    describe('createPerson', () => {
        it('should call measuring store and set batch store cache', async () => {
            const result = await shadowManager.createPerson(
                DateTime.now(),
                { new_prop: 'value' },
                {},
                {},
                teamId,
                null,
                false,
                'new-id',
                [{ distinctId: 'test-distinct', version: 0 }]
            )
            expect(result).toBeDefined()
            expect(result[0].id).toBe('new-id')

            await shadowManager.flush()
            expect(db.createPerson).toHaveBeenCalledTimes(1)

            // Check that batch store cache was set
            const updateCache = batchStoreForBatch.getUpdateCache()
            const cachedUpdate = updateCache.get(`${teamId}:${result[0].id}`)
            expect(cachedUpdate).toBeDefined()
        })
    })

    describe('updatePersonWithPropertiesDiffForUpdate', () => {
        it('should call both stores and track final state', async () => {
            const result = await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'new_value' },
                [],
                {},
                'test-distinct'
            )

            expect(result).toBeDefined()
            expect(result[0].properties).toEqual({ test: 'test', new_prop: 'new_value' })

            await shadowManager.flush()
            // Only measuring store should make DB calls - batch store batches the update
            expect(db.updatePerson).toHaveBeenCalledTimes(1)
            expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(0)

            // Check that final state was tracked
            const finalStates = shadowManager.getFinalStates()
            const finalState = finalStates.get(`${teamId}:${person.id}`)
            expect(finalState).toBeDefined()
            expect(finalState?.person.properties).toEqual({ test: 'test', new_prop: 'new_value' })
            expect(finalState?.versionDisparity).toBe(false)
        })
    })

    describe('updatePersonForMerge', () => {
        it('should call both stores and track final state', async () => {
            const update = { properties: { merge_prop: 'merge_value' } }

            const result = await shadowManager.updatePersonForMerge(person, update, 'test-distinct')

            expect(result).toBeDefined()
            expect(result[0].properties).toEqual({ test: 'test', merge_prop: 'merge_value' })

            await shadowManager.flush()

            // Only measuring store should make DB calls - batch store batches the update
            expect(db.updatePerson).toHaveBeenCalledTimes(1)
            expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(0)

            // Check that final state was tracked
            const finalStates = shadowManager.getFinalStates()
            const finalState = finalStates.get(`${teamId}:${person.id}`)
            expect(finalState).toBeDefined()
            expect(finalState?.person.properties).toEqual({ test: 'test', merge_prop: 'merge_value' })
            expect(finalState?.versionDisparity).toBe(false)
        })
    })

    describe('deletePerson', () => {
        it('should call measuring store and clear batch store cache', async () => {
            // First add person to caches
            await shadowManager.fetchForUpdate(teamId, 'test-distinct')

            const result = await shadowManager.deletePerson(person, 'test-distinct')

            await shadowManager.flush()

            expect(result).toEqual([])
            expect(db.deletePerson).toHaveBeenCalledWith(person, undefined)
            expect(db.deletePerson).toHaveBeenCalledTimes(1)

            // Check that final state was set to null
            const finalStates = shadowManager.getFinalStates()
            const finalState = finalStates.get(`${teamId}:${person.id}`)
            expect(finalState).toBeNull()

            // Check that batch store cache was cleared
            const updateCache = batchStoreForBatch.getUpdateCache()
            expect(updateCache.get('1:test-distinct')).toBeUndefined()
        })
    })

    describe('flush and compareFinalStates', () => {
        const logger = require('../../../utils/logger').logger

        beforeEach(() => {
            jest.clearAllMocks()
        })

        it('should do same outcome by default', async () => {
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'value' },
                [],
                {},
                'test-distinct'
            )

            await shadowManager.flush()

            // Verify flush makes no DB writes
            expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(0)
            expect(db.updatePerson).toHaveBeenCalledTimes(1)
            expect(db.createPerson).toHaveBeenCalledTimes(0)
            expect(db.deletePerson).toHaveBeenCalledTimes(0)
            expect(db.fetchPerson).toHaveBeenCalledTimes(0)

            const metrics = shadowManager.getShadowMetrics()
            expect(metrics).toBeDefined()
            expect(metrics!.totalComparisons).toBe(1)
            expect(metrics!.sameOutcomeSameBatch).toBe(1)
            expect(metrics!.differentOutcomeSameBatch).toBe(0)
            expect(metrics!.differentOutcomeDifferentBatch).toBe(0)
            expect(metrics!.sameOutcomeDifferentBatch).toBe(0)
            expect(metrics!.logicErrors).toHaveLength(0)
            expect(metrics!.concurrentModifications).toHaveLength(0)
        })

        it('should detect same outcome same batch (ideal case)', async () => {
            // Set up scenario where both stores produce identical results
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'value' },
                [],
                {},
                'test-distinct'
            )

            // Manually set batch cache to match measuring result
            const expectedPerson = { ...person, properties: { test: 'test', new_prop: 'value' }, version: 2 }
            const personUpdate = fromInternalPerson(expectedPerson, 'test-distinct')
            batchStoreForBatch.setCachedPersonForUpdate(teamId, 'test-distinct', personUpdate)

            await shadowManager.flush()

            const metricsData = shadowManager.getShadowMetrics()
            expect(metricsData).toBeDefined()
            expect(metricsData!.totalComparisons).toBe(1)
            expect(metricsData!.sameOutcomeSameBatch).toBe(1)
            expect(metricsData!.differentOutcomeSameBatch).toBe(0)
            expect(metricsData!.differentOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.sameOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.logicErrors).toHaveLength(0)
            expect(metricsData!.concurrentModifications).toHaveLength(0)
        })

        it('should detect logic errors (different outcome same batch)', async () => {
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'value' },
                [],
                {},
                'test-distinct'
            )

            // Manually set batch cache to have different result (simulating logic error)
            const differentPerson = {
                ...person,
                properties: { test: 'test', different_prop: 'different_value' },
                version: 2,
            }
            const personUpdate = fromInternalPerson(differentPerson, 'test-distinct')
            batchStoreForBatch.setCachedPersonForUpdate(teamId, 'test-distinct', personUpdate)

            await shadowManager.flush()

            const metricsData = shadowManager.getShadowMetrics()
            expect(metricsData).toBeDefined()
            expect(metricsData!.totalComparisons).toBe(1)
            expect(metricsData!.sameOutcomeSameBatch).toBe(0)
            expect(metricsData!.differentOutcomeSameBatch).toBe(1)
            expect(metricsData!.differentOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.sameOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.logicErrors).toHaveLength(1)
            expect(metricsData!.logicErrors[0].key).toBe(`${teamId}:${person.id}`)
            expect(metricsData!.logicErrors[0].differences.length).toBeGreaterThan(0)
            expect(metricsData!.concurrentModifications).toHaveLength(0)

            // Test that reportBatch logs the errors
            shadowManager.reportBatch()
            expect(logger.info).toHaveBeenCalledWith(
                'Shadow mode detected logic errors in batch writing store',
                expect.objectContaining({
                    logicErrorCount: 1,
                    errorRate: '100.00%',
                })
            )
        })

        it('should detect concurrent modifications with version disparity', async () => {
            // Mock version disparity in measuring store
            db.updatePerson = jest.fn().mockImplementation((person, update) => {
                const personCopy = { ...person, ...update, version: person.version + 1 }
                return Promise.resolve([personCopy, [], true]) // version disparity = true
            })

            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'value' },
                [],
                {},
                'test-distinct'
            )

            // Set batch cache to have different result (simulating concurrent modification)
            const concurrentPerson = {
                ...person,
                properties: { test: 'test', concurrent_prop: 'concurrent_value' },
                version: 3,
            }
            const personUpdate = fromInternalPerson(concurrentPerson, 'test-distinct')
            batchStoreForBatch.setCachedPersonForUpdate(teamId, 'test-distinct', personUpdate)

            await shadowManager.flush()

            const metricsData = shadowManager.getShadowMetrics()
            expect(metricsData).toBeDefined()
            expect(metricsData!.totalComparisons).toBe(1)
            expect(metricsData!.sameOutcomeSameBatch).toBe(0)
            expect(metricsData!.differentOutcomeSameBatch).toBe(0)
            expect(metricsData!.differentOutcomeDifferentBatch).toBe(1)
            expect(metricsData!.sameOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.logicErrors).toHaveLength(0)
            expect(metricsData!.concurrentModifications).toHaveLength(1)
            expect(metricsData!.concurrentModifications[0].type).toBe('different_outcome')
            expect(metricsData!.concurrentModifications[0].key).toBe(`${teamId}:${person.id}`)

            // Test that reportBatch logs the concurrent modifications
            shadowManager.reportBatch()
            expect(logger.warn).toHaveBeenCalledWith(
                'Shadow mode detected concurrent modifications during batch processing',
                expect.objectContaining({
                    concurrentModificationCount: 1,
                    differentOutcomes: 1,
                    sameOutcomes: 0,
                })
            )
        })

        it('should handle missing persons in batch cache', async () => {
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'value' },
                [],
                {},
                'test-distinct'
            )

            // Set batch cache to null (simulating missing person)
            batchStoreForBatch.clearAllCachesForDistinctId(teamId, 'test-distinct')

            await shadowManager.flush()

            const metricsData = shadowManager.getShadowMetrics()
            expect(metricsData).toBeDefined()
            expect(metricsData!.totalComparisons).toBe(1)
            expect(metricsData!.sameOutcomeSameBatch).toBe(0)
            expect(metricsData!.differentOutcomeSameBatch).toBe(1) // null vs person = different outcome
            expect(metricsData!.differentOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.sameOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.logicErrors).toHaveLength(1)
            expect(metricsData!.concurrentModifications).toHaveLength(0)
        })

        it('should handle multiple updates for same person', async () => {
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'value1' },
                [],
                {},
                'test-distinct'
            )
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { new_prop: 'value2' },
                [],
                {},
                'test-distinct'
            )

            await shadowManager.flush()

            // Verify flush makes no DB writes
            expect(db.updatePersonAssertVersion).toHaveBeenCalledTimes(0)
            expect(db.updatePerson).toHaveBeenCalledTimes(2)
            expect(db.createPerson).toHaveBeenCalledTimes(0)
            expect(db.deletePerson).toHaveBeenCalledTimes(0)
            expect(db.fetchPerson).toHaveBeenCalledTimes(0)

            const metricsData = shadowManager.getShadowMetrics()
            expect(metricsData).toBeDefined()
            expect(metricsData!.totalComparisons).toBe(1)
            expect(metricsData!.sameOutcomeSameBatch).toBe(1)
            expect(metricsData!.differentOutcomeSameBatch).toBe(0)
            expect(metricsData!.differentOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.sameOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.logicErrors).toHaveLength(0)
            expect(metricsData!.concurrentModifications).toHaveLength(0)
        })

        it('should handle updates after create person', async () => {
            const [personResult] = await shadowManager.createPerson(
                person.created_at,
                person.properties,
                person.properties_last_updated_at,
                person.properties_last_operation || {},
                person.team_id,
                person.is_user_id,
                person.is_identified,
                person.id,
                [{ distinctId: 'test-distinct', version: 0 }]
            )
            const [personUpdateResult] = await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                personResult,
                { new_prop1: 'value1' },
                [],
                {},
                'test-distinct'
            )
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                personUpdateResult,
                { new_prop2: 'value2' },
                [],
                {},
                'test-distinct'
            )

            await shadowManager.flush()

            const metricsData = shadowManager.getShadowMetrics()
            expect(metricsData).toBeDefined()
            expect(metricsData!.totalComparisons).toBe(1)
            expect(metricsData!.sameOutcomeSameBatch).toBe(1)
            expect(metricsData!.differentOutcomeSameBatch).toBe(0)
            expect(metricsData!.differentOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.sameOutcomeDifferentBatch).toBe(0)
            expect(metricsData!.logicErrors).toHaveLength(0)
            expect(metricsData!.concurrentModifications).toHaveLength(0)
        })

        it('should report comprehensive batch metrics and logging', async () => {
            // Set up a complex scenario with multiple types of outcomes
            // Person 1: Same outcome, same batch (ideal case)
            const person1 = { ...person, id: 'person1-id' }
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person1,
                { prop1: 'value1' },
                [],
                {},
                'person1-distinct'
            )
            const expectedPerson1 = { ...person1, properties: { test: 'test', prop1: 'value1' }, version: 2 }
            const personUpdate1 = fromInternalPerson(expectedPerson1, 'person1-distinct')
            batchStoreForBatch.setCachedPersonForUpdate(teamId, 'person1-distinct', personUpdate1)

            // Person 2: Different outcome, same batch (logic error)
            const person2 = { ...person, id: 'person2-id' }
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person2,
                { prop2: 'value2' },
                [],
                {},
                'person2-distinct'
            )
            const differentPerson2 = { ...person2, properties: { test: 'test', wrong_prop: 'wrong_value' }, version: 3 }
            const personUpdate2 = fromInternalPerson(differentPerson2, 'person2-distinct')
            batchStoreForBatch.setCachedPersonForUpdate(teamId, 'person2-distinct', personUpdate2)

            // Person 3: Concurrent modification (version disparity)
            // Mock version disparity for person3 only
            db.updatePerson = jest.fn().mockImplementation((personInput, update) => {
                if (personInput.id === 'person3-id') {
                    const personCopy = {
                        ...personInput,
                        properties: { ...personInput.properties, ...(update.properties || {}) },
                        version: personInput.version + 1,
                        id: 'person3-id',
                    }
                    return Promise.resolve([personCopy, [], true]) // version disparity = true
                } else {
                    const updatedPerson = {
                        ...personInput,
                        properties: { ...personInput.properties, ...(update.properties || {}) },
                        version: personInput.version + 1,
                    }
                    return Promise.resolve([updatedPerson, [], false])
                }
            })

            const person3 = { ...person, id: 'person3-id' }
            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person3,
                { prop3: 'value3' },
                [],
                {},
                'person3-distinct'
            )
            const concurrentPerson3 = {
                ...person3,
                properties: { test: 'test', concurrent_prop: 'concurrent_value' },
                version: 4,
            }
            const personUpdate3 = fromInternalPerson(concurrentPerson3, 'person3-distinct')
            batchStoreForBatch.setCachedPersonForUpdate(teamId, 'person3-distinct', personUpdate3)

            await shadowManager.flush()

            // Verify metrics were calculated correctly
            const metricsData = shadowManager.getShadowMetrics()
            expect(metricsData.totalComparisons).toBe(3)
            expect(metricsData.sameOutcomeSameBatch).toBe(1) // person1
            expect(metricsData.differentOutcomeSameBatch).toBe(1) // person2
            expect(metricsData.differentOutcomeDifferentBatch).toBe(1) // person3
            expect(metricsData.sameOutcomeDifferentBatch).toBe(0)
            expect(metricsData.logicErrors).toHaveLength(1)
            expect(metricsData.concurrentModifications).toHaveLength(1)

            // Test reportBatch logging
            shadowManager.reportBatch()

            // Verify main info log was called with correct metrics
            expect(logger.info).toHaveBeenCalledWith(
                'Shadow mode person batch comparison completed',
                expect.objectContaining({
                    totalComparisons: 3,
                    sameOutcomeSameBatch: 1,
                    differentOutcomeSameBatch: 1,
                    differentOutcomeDifferentBatch: 1,
                    sameOutcomeDifferentBatch: 0,
                    logicErrorRate: '33.33%', // 1/3 * 100
                    concurrentModificationRate: '33.33%', // 1/3 * 100
                })
            )

            // Verify logic error was logged
            expect(logger.info).toHaveBeenCalledWith(
                'Shadow mode detected logic errors in batch writing store',
                expect.objectContaining({
                    logicErrorCount: 1,
                    totalComparisons: 3,
                    errorRate: '33.33%',
                    sampleErrors: expect.arrayContaining([
                        expect.objectContaining({
                            key: `${teamId}:${person2.id}`,
                            differences: expect.any(Array),
                            mainPersonId: expect.any(String),
                            secondaryPersonId: expect.any(String),
                        }),
                    ]),
                })
            )

            // Verify concurrent modification was logged
            expect(logger.warn).toHaveBeenCalledWith(
                'Shadow mode detected concurrent modifications during batch processing',
                expect.objectContaining({
                    concurrentModificationCount: 1,
                    differentOutcomes: 1,
                    sameOutcomes: 0,
                    concurrentModificationRate: '33.33%',
                    sampleModifications: expect.arrayContaining([
                        expect.objectContaining({
                            key: `${teamId}:${person3.id}`,
                            type: 'different_outcome',
                            mainPersonId: expect.any(String),
                            secondaryPersonId: expect.any(String),
                        }),
                    ]),
                })
            )
        })

        it('should handle addDistinctId ', async () => {
            const teamId = 126617
            const personId = '483a46b9-aea8-5205-828e-85a6f77ad6b0'
            const distinctId = '0197a209-f567-7daa-8810-900f7c7f7b5d'

            const existingPerson: InternalPerson = {
                id: personId,
                uuid: 'existing-person-uuid',
                created_at: DateTime.fromISO('2025-04-11T00:22:49.998Z'),
                team_id: teamId,
                properties: {
                    $os: 'Android',
                    $creator_event_uuid: '0196223a-5299-72a2-b7cd-3c9cc03d6869',
                },
                properties_last_updated_at: {
                    $os: '2025-04-11T00:22:49.998Z',
                    $app_name: '2025-04-11T00:22:49.998Z',
                },
                properties_last_operation: {},
                is_user_id: null,
                is_identified: true,
                version: 1,
            }

            // Step 1: Add a distinct ID to an existing person
            // This simulates the production scenario where we're adding a new distinct ID
            await shadowManager.addDistinctId(existingPerson, distinctId, 0)

            // Step 2: Flush to trigger comparison
            await shadowManager.flush()

            const metrics = shadowManager.getShadowMetrics()
            const finalStates = shadowManager.getFinalStates()
            const finalState = finalStates.get(`${teamId}:${existingPerson.id}`)

            // Verify the final state is tracked correctly
            expect(finalState?.person).toEqual(existingPerson)
            expect(finalState?.operations).toEqual([
                {
                    type: 'addDistinctId',
                    timestamp: expect.any(Number),
                    distinctId: distinctId,
                    version: existingPerson.version,
                },
            ])

            expect(metrics.totalComparisons).toBe(1)
            expect(metrics.sameOutcomeSameBatch).toBe(1)
            expect(metrics.differentOutcomeSameBatch).toBe(0)
            expect(metrics.logicErrors).toHaveLength(0)
        })

        it('should handle createPerson followed by moveDistinctIds', async () => {
            const teamId = 61953
            const personId = 'person-id'

            // Mock the main store to successfully create a person
            const createdPerson: InternalPerson = {
                id: personId,
                created_at: DateTime.fromISO('2025-06-23T13:05:07.461Z'),
                properties: {
                    $creator_event_uuid: '01979ce4-7561-7b81-b188-4d2a6e9bbae3',
                },
                team_id: teamId,
                is_user_id: null,
                is_identified: false,
                uuid: 'created-person-uuid',
                properties_last_updated_at: {},
                properties_last_operation: {},
                version: 1,
            }

            // Create another person that will be the merge target
            const targetPerson: InternalPerson = {
                ...createdPerson,
                id: 'target-person-id',
                uuid: 'target-person-uuid',
                version: 2,
            }

            db.createPerson = jest.fn().mockResolvedValue([createdPerson, []])

            // Create shadow manager
            const measuringStore = new MeasuringPersonsStore(db, {
                personCacheEnabledForUpdates: true,
                personCacheEnabledForChecks: true,
            })
            const batchStore = new BatchWritingPersonsStore(db)
            const measuringStoreForBatch = measuringStore.forBatch() as MeasuringPersonsStoreForBatch
            const batchStoreForBatch = batchStore.forBatch() as BatchWritingPersonsStoreForBatch
            const shadowManager = new PersonStoreManagerForBatch(measuringStoreForBatch, batchStoreForBatch)
            const distinctId = new UUID7().toString()

            // Step 1: Create person - this sets batch cache
            await shadowManager.createPerson(
                createdPerson.created_at,
                createdPerson.properties,
                createdPerson.properties_last_updated_at,
                createdPerson.properties_last_operation || {},
                teamId,
                null,
                false,
                personId,
                [{ distinctId: distinctId, version: 0 }]
            )

            // Verify batch cache was set after create
            const batchUpdateCache = batchStoreForBatch.getUpdateCache()
            expect(batchUpdateCache.get(`${teamId}:${createdPerson.id}`)).toBeDefined()

            // Step 2: Move distinct IDs (simulate merge)
            await shadowManager.moveDistinctIds(createdPerson, targetPerson, distinctId)

            // Verify batch cache is populated after moveDistinctIds
            expect(batchUpdateCache.get(`${teamId}:${createdPerson.id}`)).toBeUndefined()
            expect(batchUpdateCache.get(`${teamId}:${targetPerson.id}`)).toBeDefined()

            // Step 3: Flush and compare final states
            await shadowManager.flush()

            const metrics = shadowManager.getShadowMetrics()
            const finalStates = shadowManager.getFinalStates()
            const finalStateSource = finalStates.get(`${teamId}:${createdPerson.id}`)

            expect(finalStateSource).toBeNull()

            const finalStateTarget = finalStates.get(`${teamId}:${targetPerson.id}`)
            expect(finalStateTarget?.person).toEqual(targetPerson)
            expect(finalStateTarget?.operations).toEqual([
                {
                    type: 'moveDistinctIds',
                    timestamp: expect.any(Number),
                    distinctId: distinctId,
                    version: targetPerson.version,
                },
            ])

            expect(metrics.totalComparisons).toBe(2)
            expect(metrics.differentOutcomeSameBatch).toBe(0)
            expect(metrics.logicErrors).toHaveLength(0)
            expect(metrics.sameOutcomeSameBatch).toBe(2)
        })

        it('should handle fetchForUpdate → updatePersonForMerge → moveDistinctIds sequence (source person)', async () => {
            // Create a person with some properties
            const sourcePerson: InternalPerson = {
                ...person,
                id: 'source-id',
                properties: {
                    test: 'test',
                    existing_prop: 'existing_value',
                },
                version: 4,
            }

            const targetPerson: InternalPerson = {
                ...person,
                id: 'target-id',
                properties: {
                    target_prop: 'target_value',
                },
                version: 5,
                is_identified: true,
            }

            // Mock DB to return the source person for fetchForUpdate
            db.fetchPerson = jest.fn().mockResolvedValue(sourcePerson)

            // Mock updatePerson to simulate merge operation
            db.updatePerson = jest.fn().mockImplementation((person, update) => {
                const updatedPerson = {
                    ...person,
                    ...update,
                    properties: { ...person.properties, ...update.properties },
                    version: person.version + 1,
                }
                return Promise.resolve([updatedPerson, [], false])
            })

            // Step 1: fetchForUpdate
            const fetchedPerson = await shadowManager.fetchForUpdate(teamId, 'test-distinct')
            expect(fetchedPerson).toEqual(sourcePerson)

            // Step 2: updatePersonForMerge - merge additional properties
            const mergeUpdate = {
                properties: {
                    merged_prop: 'merged_value',
                },
                is_identified: true,
            }
            const [mergedPerson] = await shadowManager.updatePersonForMerge(sourcePerson, mergeUpdate, 'test-distinct')

            // Verify the merge worked
            expect(mergedPerson.properties.merged_prop).toBe('merged_value')
            expect(mergedPerson.properties.existing_prop).toBe('existing_value')
            expect(mergedPerson.is_identified).toBe(true)

            // Step 3: moveDistinctIds - simulate moving distinct IDs to target person
            await shadowManager.moveDistinctIds(sourcePerson, targetPerson, 'test-distinct')

            // Step 4: Flush and check final states
            await shadowManager.flush()

            const metrics = shadowManager.getShadowMetrics()
            const finalStates = shadowManager.getFinalStates()

            // Verify final state tracking
            const sourceState = finalStates.get(`${teamId}:${sourcePerson.id}`)
            const targetState = finalStates.get(`${teamId}:${targetPerson.id}`)

            // After moveDistinctIds, source should be null, target should have the data
            expect(sourceState).toBeNull()
            expect(targetState?.person).toEqual(targetPerson)
            expect(targetState?.operations).toContainEqual(
                expect.objectContaining({
                    type: 'moveDistinctIds',
                    distinctId: 'test-distinct',
                })
            )

            expect(metrics.logicErrors).toHaveLength(0)
        })

        it('should handle fetchForUpdate → updatePersonForMerge → moveDistinctIds sequence (target person)', async () => {
            // Create target person that we will be tracking throughout the process
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
                    rich_property: 'rich_value',
                },
                version: 4,
                is_identified: true,
            }

            // Mock DB to return the target person for fetchForUpdate
            db.fetchPerson = jest.fn().mockResolvedValue(targetPerson)

            // Mock updatePerson to simulate merge operation on target
            db.updatePerson = jest.fn().mockImplementation((person, update) => {
                const updatedPerson = {
                    ...person,
                    ...update,
                    properties: { ...person.properties, ...update.properties },
                    version: person.version + 1,
                }
                return Promise.resolve([updatedPerson, [], false])
            })

            // Step 1: fetchForUpdate on target person
            const fetchedPerson = await shadowManager.fetchForUpdate(teamId, 'target-distinct')
            expect(fetchedPerson).toEqual(targetPerson)

            // Step 2: updatePersonForMerge - merge properties from source into target
            const mergeUpdate = {
                properties: {
                    // Properties being merged from source person
                    source_prop: 'source_value',
                    rich_property: 'rich_value',
                    merged_from_source: 'merged_value',
                },
                is_identified: true,
            }
            const [mergedPerson] = await shadowManager.updatePersonForMerge(
                targetPerson,
                mergeUpdate,
                'target-distinct'
            )

            // Verify the merge worked on target
            expect(mergedPerson.properties.source_prop).toBe('source_value')
            expect(mergedPerson.properties.target_prop).toBe('target_value') // Original target props preserved
            expect(mergedPerson.properties.rich_property).toBe('rich_value')
            expect(mergedPerson.is_identified).toBe(true)

            // Step 3: moveDistinctIds - simulate moving distinct IDs FROM source TO target
            // After this, the target should receive all the data and properties
            await shadowManager.moveDistinctIds(sourcePerson, targetPerson, 'target-distinct')

            // Step 4: Flush and check final states
            await shadowManager.flush()

            const metrics = shadowManager.getShadowMetrics()
            const finalStates = shadowManager.getFinalStates()

            // Verify final state tracking
            const sourceState = finalStates.get(`${teamId}:${sourcePerson.id}`)
            const targetState = finalStates.get(`${teamId}:${targetPerson.id}`)

            // After moveDistinctIds, source should be null, target should still have the merged data
            expect(sourceState).toBeNull()
            // Verify the target contains the merged properties
            expect(targetState?.person?.properties).toEqual(mergedPerson.properties)
            expect(targetState?.person?.is_identified).toBe(mergedPerson.is_identified)
            expect(targetState?.person?.id).toBe(mergedPerson.id)
            expect(targetState?.operations).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        type: 'fetchForUpdate',
                        distinctId: 'target-distinct',
                    }),
                    expect.objectContaining({
                        type: 'updatePersonForMerge',
                        distinctId: 'target-distinct',
                    }),
                    expect.objectContaining({
                        type: 'moveDistinctIds',
                        distinctId: 'target-distinct',
                    }),
                ])
            )

            // Check for any logic errors - this is where the bug might manifest
            // The bug would be that properties from the merge are missing in the measuring store
            if (metrics.logicErrors.length > 0) {
                const logicError = metrics.logicErrors[0]
                console.log('Detected target person logic error:', logicError.differences)

                // Check if we're missing properties that should have been merged
                const missingProperties = logicError.differences.filter(
                    (diff) =>
                        diff.includes('missing in measuring store') &&
                        (diff.includes('source_prop') ||
                            diff.includes('rich_property') ||
                            diff.includes('merged_from_source'))
                )

                if (missingProperties.length > 0) {
                    console.log(
                        'Bug reproduced! Properties lost in target person after moveDistinctIds:',
                        missingProperties
                    )
                }
            }
        })
    })

    describe('compareUpdateResults', () => {
        const logger = require('../../../utils/logger').logger
        const { personShadowModeReturnIntermediateOutcomeCounter } = require('./metrics')

        beforeEach(() => {
            jest.clearAllMocks()
            // Mock the metric counter
            personShadowModeReturnIntermediateOutcomeCounter.labels = jest.fn().mockReturnValue({
                inc: jest.fn(),
            })
        })

        it('should track consistent results and log debug message', async () => {
            // Mock both stores to return the same result
            const expectedPerson = { ...person, properties: { test: 'test', test_prop: 'test_value' }, version: 2 }
            db.updatePerson = jest.fn().mockResolvedValue([expectedPerson, [], false])

            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { test_prop: 'test_value' },
                [],
                {},
                'test-distinct'
            )

            // Verify metric was incremented for consistent outcome
            expect(personShadowModeReturnIntermediateOutcomeCounter.labels).toHaveBeenCalledWith(
                'updatePersonWithPropertiesDiffForUpdate',
                'consistent'
            )
        })

        it('should track inconsistent results and log error message for updatePersonWithPropertiesDiffForUpdate', async () => {
            // Mock main store to return one result
            const mainPerson = { ...person, properties: { test: 'test', test_prop: 'test_value' }, version: 2 }
            db.updatePerson = jest.fn().mockResolvedValue([mainPerson, [], false])

            // Mock secondary store to return different result by manipulating its internal state
            const secondaryPerson = {
                ...person,
                properties: { test: 'test', different_prop: 'different_value' },
                version: 2,
            }

            // We'll need to manually set up the secondary store to return different data
            // Since the secondary store doesn't actually call the DB, we need to mock its updatePersonWithPropertiesDiffForUpdate method
            const originalUpdatePersonWithPropertiesDiffForUpdate =
                batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = jest
                .fn()
                .mockResolvedValue([secondaryPerson, [], false])

            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { test_prop: 'test_value' },
                [],
                {},
                'test-distinct'
            )

            // Restore original method
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = originalUpdatePersonWithPropertiesDiffForUpdate

            // Verify metric was incremented for inconsistent outcome
            expect(personShadowModeReturnIntermediateOutcomeCounter.labels).toHaveBeenCalledWith(
                'updatePersonWithPropertiesDiffForUpdate',
                'inconsistent'
            )

            // Verify error log was called with detailed information
            expect(logger.info).toHaveBeenCalledWith(
                'updatePersonWithPropertiesDiffForUpdate returned inconsistent results between stores',
                expect.objectContaining({
                    key: `${teamId}:${person.id}`,
                    teamId: 1,
                    methodName: 'updatePersonWithPropertiesDiffForUpdate',
                    samePersonResult: false,
                    differences: expect.arrayContaining([expect.stringContaining('person.properties')]),
                    mainPersonId: mainPerson.id,
                    secondaryPersonId: secondaryPerson.id,
                    mainVersionDisparity: false,
                })
            )
        })

        it('should track inconsistent results and log error message for updatePersonForMerge', async () => {
            const update = { properties: { merge_prop: 'merge_value' } }

            // Mock main store to return one result
            const mainPerson = { ...person, properties: { test: 'test', merge_prop: 'merge_value' }, version: 2 }
            db.updatePerson = jest.fn().mockResolvedValue([mainPerson, [], false])

            // Mock secondary store to return different result
            const secondaryPerson = { ...person, properties: { test: 'test', wrong_merge: 'wrong_value' }, version: 2 }
            const originalUpdatePersonForMerge = batchStoreForBatch.updatePersonForMerge
            batchStoreForBatch.updatePersonForMerge = jest.fn().mockResolvedValue([secondaryPerson, [], false])

            await shadowManager.updatePersonForMerge(person, update, 'test-distinct')

            // Restore original method
            batchStoreForBatch.updatePersonForMerge = originalUpdatePersonForMerge

            // Verify metric was incremented for inconsistent outcome
            expect(personShadowModeReturnIntermediateOutcomeCounter.labels).toHaveBeenCalledWith(
                'updatePersonForMerge',
                'inconsistent'
            )

            // Verify error log was called
            expect(logger.info).toHaveBeenCalledWith(
                'updatePersonForMerge returned inconsistent results between stores',
                expect.objectContaining({
                    key: `${teamId}:${person.id}`,
                    teamId: 1,
                    methodName: 'updatePersonForMerge',
                    samePersonResult: false,
                    differences: expect.arrayContaining([expect.stringContaining('person.properties')]),
                    mainPersonId: mainPerson.id,
                    secondaryPersonId: secondaryPerson.id,
                })
            )
        })

        it('should handle null vs non-null person comparison', async () => {
            // Mock main store to return a person
            const mainPerson = { ...person, properties: { test: 'test', test_prop: 'test_value' }, version: 2 }
            db.updatePerson = jest.fn().mockResolvedValue([mainPerson, [], false])

            // Mock secondary store to return null (no person found)
            const originalUpdatePersonWithPropertiesDiffForUpdate =
                batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = jest.fn().mockResolvedValue([null, [], false])

            await shadowManager.updatePersonWithPropertiesDiffForUpdate(
                person,
                { test_prop: 'test_value' },
                [],
                {},
                'test-distinct'
            )

            // Restore original method
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = originalUpdatePersonWithPropertiesDiffForUpdate

            // Verify metric was incremented for inconsistent outcome
            expect(personShadowModeReturnIntermediateOutcomeCounter.labels).toHaveBeenCalledWith(
                'updatePersonWithPropertiesDiffForUpdate',
                'inconsistent'
            )

            // Verify error log includes null comparison
            expect(logger.info).toHaveBeenCalledWith(
                'updatePersonWithPropertiesDiffForUpdate returned inconsistent results between stores',
                expect.objectContaining({
                    samePersonResult: false,
                    mainPersonId: mainPerson.id,
                    secondaryPersonId: undefined,
                })
            )
        })

        it('should detect differences in nested properties', async () => {
            const update = {
                properties: {
                    nested: {
                        deep: {
                            prop: 'value',
                        },
                    },
                },
            }

            // Mock main store result
            const mainPerson = {
                ...person,
                properties: {
                    test: 'test',
                    nested: {
                        deep: {
                            prop: 'value',
                        },
                    },
                },
                version: 2,
            }
            db.updatePerson = jest.fn().mockResolvedValue([mainPerson, [], false])

            // Mock secondary store with different nested value
            const secondaryPerson = {
                ...person,
                properties: {
                    test: 'test',
                    nested: {
                        deep: {
                            prop: 'different_value',
                        },
                    },
                },
                version: 2,
            }
            const originalUpdatePersonWithPropertiesDiffForUpdate =
                batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = jest
                .fn()
                .mockResolvedValue([secondaryPerson, [], false])

            await shadowManager.updatePersonWithPropertiesDiffForUpdate(person, update, [], {}, 'test-distinct')

            // Restore original method
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = originalUpdatePersonWithPropertiesDiffForUpdate

            // Verify specific nested property difference is captured
            expect(logger.info).toHaveBeenCalledWith(
                'updatePersonWithPropertiesDiffForUpdate returned inconsistent results between stores',
                expect.objectContaining({
                    differences: expect.arrayContaining([
                        expect.stringContaining('person.properties.nested.deep.prop'),
                    ]),
                })
            )
        })

        it('should ignore version differences in comparison', async () => {
            const update = { properties: { test_prop: 'test_value' } }

            // Mock main store to return person with version 2
            const mainPerson = { ...person, properties: { test: 'test', test_prop: 'test_value' }, version: 2 }
            db.updatePerson = jest.fn().mockResolvedValue([mainPerson, [], false])

            // Mock secondary store to return same person but with version 3 (should be ignored)
            const secondaryPerson = { ...person, properties: { test: 'test', test_prop: 'test_value' }, version: 3 }
            const originalUpdatePersonWithPropertiesDiffForUpdate =
                batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = jest
                .fn()
                .mockResolvedValue([secondaryPerson, [], false])

            await shadowManager.updatePersonWithPropertiesDiffForUpdate(person, update, [], {}, 'test-distinct')

            // Restore original method
            batchStoreForBatch.updatePersonWithPropertiesDiffForUpdate = originalUpdatePersonWithPropertiesDiffForUpdate

            // Verify result is considered consistent despite version difference
            expect(personShadowModeReturnIntermediateOutcomeCounter.labels).toHaveBeenCalledWith(
                'updatePersonWithPropertiesDiffForUpdate',
                'consistent'
            )
        })
    })
})
