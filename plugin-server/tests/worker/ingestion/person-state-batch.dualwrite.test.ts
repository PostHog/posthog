import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Clickhouse } from '~/tests/helpers/clickhouse'
import { Hub, InternalPerson, Team } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { defaultRetryConfig } from '../../../src/utils/retries'
import { UUIDT } from '../../../src/utils/utils'
import { uuidFromDistinctId } from '../../../src/worker/ingestion/person-uuid'
import { BatchWritingPersonsStoreForBatch } from '../../../src/worker/ingestion/persons/batch-writing-person-store'
import { PersonContext } from '../../../src/worker/ingestion/persons/person-context'
import { PersonEventProcessor } from '../../../src/worker/ingestion/persons/person-event-processor'
import { PersonPropertyService } from '../../../src/worker/ingestion/persons/person-property-service'
import { PersonMergeService } from '../../../src/worker/ingestion/persons/person-merge-service'
import { PostgresPersonRepository } from '../../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { PostgresDualWritePersonRepository } from '../../../src/worker/ingestion/persons/repositories/postgres-dualwrite-person-repository'
import {
    createOrganization,
    createTeam,
    fetchPostgresPersons,
    getTeam,
    resetTestDatabase,
} from '../../helpers/sql'
import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'
import { setupMigrationDb, cleanupPrepared } from '../../../src/worker/ingestion/persons/repositories/test-helpers'

jest.setTimeout(30000)

describe('PersonState dual-write compatibility', () => {
    let hub: Hub
    let clickhouse: Clickhouse
    let singleWriteRepository: PostgresPersonRepository
    let dualWriteRepository: PostgresDualWritePersonRepository
    let mockProducerObserver: KafkaProducerObserver
    
    let teamId: number
    let mainTeam: Team
    let organizationId: string
    
    let timestamp: DateTime
    
    beforeAll(async () => {
        hub = await createHub({})
        mockProducerObserver = new KafkaProducerObserver(hub.kafkaProducer)
        mockProducerObserver.resetKafkaProducer()
        
        clickhouse = Clickhouse.create()
        await clickhouse.exec('SYSTEM STOP MERGES')
    })
    
    beforeEach(async () => {
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        await setupMigrationDb(hub.db.postgresPersonMigration)
        
        organizationId = await createOrganization(hub.db.postgres)
        teamId = await createTeam(hub.db.postgres, organizationId)
        mainTeam = (await getTeam(hub, teamId))!
        timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
        
        singleWriteRepository = new PostgresPersonRepository(hub.db.postgres)
        dualWriteRepository = new PostgresDualWritePersonRepository(hub.db.postgres, hub.db.postgresPersonMigration)
        
        defaultRetryConfig.RETRY_INTERVAL_DEFAULT = 0
        
        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)
    })
    
    afterEach(async () => {
        await cleanupPrepared(hub)
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })
    
    afterAll(async () => {
        await closeHub(hub)
        await clickhouse.exec('SYSTEM START MERGES')
        clickhouse.close()
    })
    
    function createPersonProcessor(
        repository: PostgresPersonRepository | PostgresDualWritePersonRepository,
        event: Partial<PluginEvent>,
        processPerson = true,
        timestampParam = timestamp,
        team = mainTeam
    ) {
        const fullEvent = {
            team_id: teamId,
            properties: {},
            ...event,
        }
        
        const personsStore = new BatchWritingPersonsStoreForBatch(
            repository,
            hub.db.kafkaProducer
        )
        
        const context = new PersonContext(
            fullEvent as PluginEvent,
            team,
            event.distinct_id!,
            timestampParam,
            processPerson,
            hub.db.kafkaProducer,
            personsStore,
            0
        )
        
        const processor = new PersonEventProcessor(
            context,
            new PersonPropertyService(context),
            new PersonMergeService(context)
        )
        
        return { processor, personsStore }
    }
    
    async function fetchPostgresPersonsH() {
        return await fetchPostgresPersons(hub.db, teamId)
    }
    
    describe('Basic person creation', () => {
        it('creates person identically with single-write and dual-write repositories', async () => {
            const singleDistinctId = 'single-test-user-1'
            const dualDistinctId = 'dual-test-user-1'
            
            const singleEvent: Partial<PluginEvent> = {
                distinct_id: singleDistinctId,
                properties: {
                    $set: { name: 'Test User', email: 'test@example.com' }
                }
            }
            
            const dualEvent: Partial<PluginEvent> = {
                distinct_id: dualDistinctId,
                properties: {
                    $set: { name: 'Test User', email: 'test@example.com' }
                }
            }
            
            const { processor: singleProcessor, personsStore: singleStore } = createPersonProcessor(singleWriteRepository, singleEvent)
            const { processor: dualProcessor, personsStore: dualStore } = createPersonProcessor(dualWriteRepository, dualEvent)
            
            const [singleResult, dualResult] = await Promise.all([
                singleProcessor.processEvent(),
                dualProcessor.processEvent()
            ])
            
            await Promise.all([
                singleStore.flush(),
                dualStore.flush()
            ])
            
            expect(singleResult).toBeDefined()
            expect(dualResult).toBeDefined()
            
            const postgresPersons = await fetchPostgresPersonsH()
            expect(postgresPersons.length).toBe(2)
            
            const singlePerson = postgresPersons.find((p: InternalPerson) => 
                p.uuid === uuidFromDistinctId(teamId, singleDistinctId)
            )
            const dualPerson = postgresPersons.find((p: InternalPerson) => 
                p.uuid === uuidFromDistinctId(teamId, dualDistinctId)
            )
            
            expect(singlePerson).toBeDefined()
            expect(dualPerson).toBeDefined()
            expect(singlePerson?.properties).toEqual({ name: 'Test User', email: 'test@example.com' })
            expect(dualPerson?.properties).toEqual({ name: 'Test User', email: 'test@example.com' })
        })
        
        it('handles concurrent person creation without errors', async () => {
            const distinctIds = ['user-1', 'user-2', 'user-3']
            
            const createWithRepo = async (repo: any, distinctId: string) => {
                const event: Partial<PluginEvent> = {
                    distinct_id: distinctId,
                    properties: {
                        $set: { id: distinctId }
                    }
                }
                
                const { processor, personsStore } = createPersonProcessor(repo, event)
                await processor.processEvent()
                await personsStore.flush()
            }
            
            const singlePromises = distinctIds.map(id => createWithRepo(singleWriteRepository, `single-${id}`))
            const dualPromises = distinctIds.map(id => createWithRepo(dualWriteRepository, `dual-${id}`))
            
            await expect(Promise.all([...singlePromises, ...dualPromises])).resolves.not.toThrow()
            
            const postgresPersons = await fetchPostgresPersonsH()
            expect(postgresPersons.length).toBe(6)
        })
    })
    
    describe('Person property updates', () => {
        it('updates properties identically with single-write and dual-write repositories', async () => {
            const singleDistinctId = 'single-update-test-user'
            const dualDistinctId = 'dual-update-test-user'
            const singleUuid = new UUIDT().toString()
            const dualUuid = new UUIDT().toString()
            
            const createPerson = async (repo: any, distinctId: string, uuid: string) => {
                const result = await repo.createPerson(
                    timestamp,
                    { initial: 'value' },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuid,
                    [{ distinctId, version: 0 }]
                )
                return result.person
            }
            
            const [singlePerson, dualPerson] = await Promise.all([
                createPerson(singleWriteRepository, singleDistinctId, singleUuid),
                createPerson(dualWriteRepository, dualDistinctId, dualUuid)
            ])
            
            const singleUpdateEvent: Partial<PluginEvent> = {
                distinct_id: singleDistinctId,
                properties: {
                    $set: { updated: 'newValue', initial: 'changed' }
                }
            }
            
            const dualUpdateEvent: Partial<PluginEvent> = {
                distinct_id: dualDistinctId,
                properties: {
                    $set: { updated: 'newValue', initial: 'changed' }
                }
            }
            
            const { processor: singleProcessor, personsStore: singleStore } = createPersonProcessor(
                singleWriteRepository, 
                singleUpdateEvent
            )
            const { processor: dualProcessor, personsStore: dualStore } = createPersonProcessor(
                dualWriteRepository,
                dualUpdateEvent
            )
            
            singleProcessor.context.person = singlePerson
            dualProcessor.context.person = dualPerson
            
            await Promise.all([
                singleProcessor.processEvent(),
                dualProcessor.processEvent()
            ])
            
            await Promise.all([
                singleStore.flush(),
                dualStore.flush()
            ])
            
            const updatedSingle = await singleWriteRepository.fetchPerson(teamId, singleDistinctId)
            const updatedDual = await dualWriteRepository.fetchPerson(teamId, dualDistinctId)
            
            expect(updatedSingle?.properties).toEqual({ initial: 'changed', updated: 'newValue' })
            expect(updatedDual?.properties).toEqual({ initial: 'changed', updated: 'newValue' })
        })
    })
    
    describe('Person identification ($identify)', () => {
        it('handles $identify event identically with both repositories', async () => {
            const singleAnonId = 'single-anon-user'
            const singleUserId = 'single-identified-user'
            const dualAnonId = 'dual-anon-user'
            const dualUserId = 'dual-identified-user'
            
            const createAnonPerson = async (repo: any, anonId: string) => {
                const uuid = uuidFromDistinctId(teamId, anonId)
                const result = await repo.createPerson(
                    timestamp,
                    { anonymous: true },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuid,
                    [{ distinctId: anonId, version: 0 }]
                )
                return result.person
            }
            
            await Promise.all([
                createAnonPerson(singleWriteRepository, singleAnonId),
                createAnonPerson(dualWriteRepository, dualAnonId)
            ])
            
            const singleIdentifyEvent: Partial<PluginEvent> = {
                distinct_id: singleUserId,
                properties: {
                    $anon_distinct_id: singleAnonId,
                    $set: { email: 'user@example.com' }
                }
            }
            
            const dualIdentifyEvent: Partial<PluginEvent> = {
                distinct_id: dualUserId,
                properties: {
                    $anon_distinct_id: dualAnonId,
                    $set: { email: 'user@example.com' }
                }
            }
            
            const { processor: singleProcessor, personsStore: singleStore } = createPersonProcessor(
                singleWriteRepository,
                singleIdentifyEvent
            )
            const { processor: dualProcessor, personsStore: dualStore } = createPersonProcessor(
                dualWriteRepository,
                dualIdentifyEvent
            )
            
            await Promise.all([
                singleProcessor.processEvent(),
                dualProcessor.processEvent()
            ])
            
            await Promise.all([
                singleStore.flush(),
                dualStore.flush()
            ])
            
            const singleIdentified = await singleWriteRepository.fetchPerson(teamId, singleUserId)
            const dualIdentified = await dualWriteRepository.fetchPerson(teamId, dualUserId)
            
            expect(singleIdentified).toBeDefined()
            expect(dualIdentified).toBeDefined()
            expect(singleIdentified?.properties.email).toBe('user@example.com')
            expect(dualIdentified?.properties.email).toBe('user@example.com')
        })
    })
    
    describe('Error handling', () => {
        it('handles creation conflicts consistently between repositories', async () => {
            const uuid = new UUIDT().toString()
            const distinctId = 'conflict-test-user'
            
            await singleWriteRepository.createPerson(
                timestamp,
                { first: true },
                {},
                {},
                teamId,
                null,
                false,
                uuid,
                [{ distinctId: 'first-' + distinctId, version: 0 }]
            )
            
            await dualWriteRepository.createPerson(
                timestamp,
                { first: true },
                {},
                {},
                teamId,
                null,
                false,
                new UUIDT().toString(),
                [{ distinctId: 'dual-first-' + distinctId, version: 0 }]
            )
            
            const singleResult = await singleWriteRepository.createPerson(
                timestamp,
                { second: true },
                {},
                {},
                teamId,
                null,
                false,
                new UUIDT().toString(),
                [{ distinctId: 'first-' + distinctId, version: 0 }]
            )
            
            const dualResult = await dualWriteRepository.createPerson(
                timestamp,
                { second: true },
                {},
                {},
                teamId,
                null,
                false,
                new UUIDT().toString(),
                [{ distinctId: 'dual-first-' + distinctId, version: 0 }]
            )
            
            expect(singleResult.success).toBe(false)
            expect(dualResult.success).toBe(false)
            expect(singleResult.error).toBe('CreationConflict')
            expect(dualResult.error).toBe('CreationConflict')
        })
        
        it('handles person not found consistently', async () => {
            const distinctId = 'non-existent-user'
            
            const singlePerson = await singleWriteRepository.fetchPerson(teamId, distinctId)
            const dualPerson = await dualWriteRepository.fetchPerson(teamId, distinctId)
            
            expect(singlePerson).toBeUndefined()
            expect(dualPerson).toBeUndefined()
        })
    })
    
    describe('Process person profile flag', () => {
        it('respects $process_person_profile=false identically', async () => {
            const distinctId = 'ephemeral-user'
            const event: Partial<PluginEvent> = {
                distinct_id: distinctId,
                properties: {
                    $process_person_profile: false,
                    $set: { should_not_persist: true }
                }
            }
            
            const { processor: singleProcessor, personsStore: singleStore } = createPersonProcessor(
                singleWriteRepository,
                event,
                false
            )
            const { processor: dualProcessor, personsStore: dualStore } = createPersonProcessor(
                dualWriteRepository,
                event,
                false
            )
            
            await Promise.all([
                singleProcessor.processEvent(),
                dualProcessor.processEvent()
            ])
            
            await Promise.all([
                singleStore.flush(),
                dualStore.flush()
            ])
            
            const postgresPersons = await fetchPostgresPersonsH()
            expect(postgresPersons.length).toBe(0)
        })
    })
    
    describe('Batch operations', () => {
        it('creates multiple persons in batch consistently', async () => {
            const distinctIds = ['batch-1', 'batch-2', 'batch-3']
            
            for (const id of distinctIds) {
                const event: Partial<PluginEvent> = {
                    distinct_id: `single-${id}`,
                    properties: {
                        $set: { batch: 'single', index: id }
                    }
                }
                const { processor, personsStore } = createPersonProcessor(singleWriteRepository, event)
                await processor.processEvent()
                await personsStore.flush()
            }
            
            for (const id of distinctIds) {
                const event: Partial<PluginEvent> = {
                    distinct_id: `dual-${id}`,
                    properties: {
                        $set: { batch: 'dual', index: id }
                    }
                }
                const { processor, personsStore } = createPersonProcessor(dualWriteRepository, event)
                await processor.processEvent()
                await personsStore.flush()
            }
            
            const postgresPersons = await fetchPostgresPersonsH()
            const singlePersons = postgresPersons.filter((p: InternalPerson) => 
                p.properties.batch === 'single'
            )
            const dualPersons = postgresPersons.filter((p: InternalPerson) => 
                p.properties.batch === 'dual'
            )
            
            expect(singlePersons.length).toBe(distinctIds.length)
            expect(dualPersons.length).toBe(distinctIds.length)
            
            singlePersons.forEach(person => {
                expect(person.properties.batch).toBe('single')
                expect(distinctIds).toContain(person.properties.index)
            })
            
            dualPersons.forEach(person => {
                expect(person.properties.batch).toBe('dual')
                expect(distinctIds).toContain(person.properties.index)
            })
        })
    })
})