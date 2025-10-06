import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

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
import { PersonMergeService } from '../../../src/worker/ingestion/persons/person-merge-service'
import { createDefaultSyncMergeMode } from '../../../src/worker/ingestion/persons/person-merge-types'
import { PersonPropertyService } from '../../../src/worker/ingestion/persons/person-property-service'
import { PostgresDualWritePersonRepository } from '../../../src/worker/ingestion/persons/repositories/postgres-dualwrite-person-repository'
import { PostgresPersonRepository } from '../../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { cleanupPrepared, setupMigrationDb } from '../../../src/worker/ingestion/persons/repositories/test-helpers'
import { createOrganization, createTeam, fetchPostgresPersons, getTeam, resetTestDatabase } from '../../helpers/sql'

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

        const personsStore = new BatchWritingPersonsStoreForBatch(repository, hub.db.kafkaProducer)

        const context = new PersonContext(
            fullEvent as PluginEvent,
            team,
            event.distinct_id!,
            timestampParam,
            processPerson,
            hub.db.kafkaProducer,
            personsStore,
            0,
            createDefaultSyncMergeMode()
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
                    $set: { name: 'Test User', email: 'test@example.com' },
                },
            }

            const dualEvent: Partial<PluginEvent> = {
                distinct_id: dualDistinctId,
                properties: {
                    $set: { name: 'Test User', email: 'test@example.com' },
                },
            }

            const { processor: singleProcessor, personsStore: singleStore } = createPersonProcessor(
                singleWriteRepository,
                singleEvent
            )
            const { processor: dualProcessor, personsStore: dualStore } = createPersonProcessor(
                dualWriteRepository,
                dualEvent
            )

            const [singleResult, dualResult] = await Promise.all([
                singleProcessor.processEvent(),
                dualProcessor.processEvent(),
            ])

            await Promise.all([singleStore.flush(), dualStore.flush()])

            expect(singleResult).toBeDefined()
            expect(dualResult).toBeDefined()

            const postgresPersons = await fetchPostgresPersonsH()
            expect(postgresPersons.length).toBe(2)

            const singlePerson = postgresPersons.find(
                (p: InternalPerson) => p.uuid === uuidFromDistinctId(teamId, singleDistinctId)
            )
            const dualPerson = postgresPersons.find(
                (p: InternalPerson) => p.uuid === uuidFromDistinctId(teamId, dualDistinctId)
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
                        $set: { id: distinctId },
                    },
                }

                const { processor, personsStore } = createPersonProcessor(repo, event)
                await processor.processEvent()
                await personsStore.flush()
            }

            const singlePromises = distinctIds.map((id) => createWithRepo(singleWriteRepository, `single-${id}`))
            const dualPromises = distinctIds.map((id) => createWithRepo(dualWriteRepository, `dual-${id}`))

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
                createPerson(dualWriteRepository, dualDistinctId, dualUuid),
            ])

            const singleUpdateEvent: Partial<PluginEvent> = {
                distinct_id: singleDistinctId,
                properties: {
                    $set: { updated: 'newValue', initial: 'changed' },
                },
            }

            const dualUpdateEvent: Partial<PluginEvent> = {
                distinct_id: dualDistinctId,
                properties: {
                    $set: { updated: 'newValue', initial: 'changed' },
                },
            }

            const { processor: singleProcessor, personsStore: singleStore } = createPersonProcessor(
                singleWriteRepository,
                singleUpdateEvent
            )
            const { processor: dualProcessor, personsStore: dualStore } = createPersonProcessor(
                dualWriteRepository,
                dualUpdateEvent
            )

            // Use type assertion to access private context for testing
            ;(singleProcessor as any).context.person = singlePerson
            ;(dualProcessor as any).context.person = dualPerson

            await Promise.all([singleProcessor.processEvent(), dualProcessor.processEvent()])

            await Promise.all([singleStore.flush(), dualStore.flush()])

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
                createAnonPerson(dualWriteRepository, dualAnonId),
            ])

            const singleIdentifyEvent: Partial<PluginEvent> = {
                distinct_id: singleUserId,
                properties: {
                    $anon_distinct_id: singleAnonId,
                    $set: { email: 'user@example.com' },
                },
            }

            const dualIdentifyEvent: Partial<PluginEvent> = {
                distinct_id: dualUserId,
                properties: {
                    $anon_distinct_id: dualAnonId,
                    $set: { email: 'user@example.com' },
                },
            }

            const { processor: singleProcessor, personsStore: singleStore } = createPersonProcessor(
                singleWriteRepository,
                singleIdentifyEvent
            )
            const { processor: dualProcessor, personsStore: dualStore } = createPersonProcessor(
                dualWriteRepository,
                dualIdentifyEvent
            )

            await Promise.all([singleProcessor.processEvent(), dualProcessor.processEvent()])

            await Promise.all([singleStore.flush(), dualStore.flush()])

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

            await singleWriteRepository.createPerson(timestamp, { first: true }, {}, {}, teamId, null, false, uuid, [
                { distinctId: 'first-' + distinctId, version: 0 },
            ])

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
            if (!singleResult.success && !dualResult.success) {
                expect(singleResult.error).toBe('CreationConflict')
                expect(dualResult.error).toBe('CreationConflict')
            }
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
                    $set: { should_not_persist: true },
                },
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

            await Promise.all([singleProcessor.processEvent(), dualProcessor.processEvent()])

            await Promise.all([singleStore.flush(), dualStore.flush()])

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
                        $set: { batch: 'single', index: id },
                    },
                }
                const { processor, personsStore } = createPersonProcessor(singleWriteRepository, event)
                await processor.processEvent()
                await personsStore.flush()
            }

            for (const id of distinctIds) {
                const event: Partial<PluginEvent> = {
                    distinct_id: `dual-${id}`,
                    properties: {
                        $set: { batch: 'dual', index: id },
                    },
                }
                const { processor, personsStore } = createPersonProcessor(dualWriteRepository, event)
                await processor.processEvent()
                await personsStore.flush()
            }

            const postgresPersons = await fetchPostgresPersonsH()
            const singlePersons = postgresPersons.filter((p: InternalPerson) => p.properties.batch === 'single')
            const dualPersons = postgresPersons.filter((p: InternalPerson) => p.properties.batch === 'dual')

            expect(singlePersons.length).toBe(distinctIds.length)
            expect(dualPersons.length).toBe(distinctIds.length)

            singlePersons.forEach((person) => {
                expect(person.properties.batch).toBe('single')
                expect(distinctIds).toContain(person.properties.index)
            })

            dualPersons.forEach((person) => {
                expect(person.properties.batch).toBe('dual')
                expect(distinctIds).toContain(person.properties.index)
            })
        })
    })

    describe('Complex PersonMergeService transaction scenarios with dual-write', () => {
        describe('mergeDistinctIds-OneExists: one person exists, adding new distinct ID', () => {
            it('merges distinct IDs atomically when one person exists using PersonMergeService', async () => {
                // This test validates the real PersonMergeService.mergeDistinctIds behavior
                // when one distinct ID has an existing person and the other doesn't.
                // This is the most common merge scenario during $identify events.

                const existingDistinctId = 'existing-user-merge-svc'
                const newDistinctId = 'new-distinct-id-merge-svc'

                // Create an existing person with one distinct ID
                const existingPersonResult = await dualWriteRepository.createPerson(
                    timestamp,
                    { name: 'Existing User', email: 'user@example.com' },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuidFromDistinctId(teamId, existingDistinctId),
                    [{ distinctId: existingDistinctId, version: 0 }]
                )

                expect(existingPersonResult.success).toBe(true)
                if (!existingPersonResult.success) {
                    throw new Error('Expected person creation to succeed')
                }
                const existingPerson = existingPersonResult.person

                // Create a PersonMergeService with dual-write repository
                // We need to set up the context similar to how it's done during event processing
                const personsStore = new BatchWritingPersonsStoreForBatch(dualWriteRepository, hub.db.kafkaProducer)

                const mergeEvent: PluginEvent = {
                    team_id: teamId,
                    distinct_id: newDistinctId,
                    properties: {
                        $anon_distinct_id: existingDistinctId,
                    },
                    timestamp: timestamp.toISO(),
                    now: timestamp.toISO(),
                    event: '$identify',
                    uuid: new UUIDT().toString(),
                    ip: '',
                    site_url: '',
                } as PluginEvent

                const context = new PersonContext(
                    mergeEvent,
                    mainTeam,
                    newDistinctId,
                    timestamp,
                    true, // processPerson
                    hub.db.kafkaProducer,
                    personsStore,
                    0, // deferredUpdatesStep
                    createDefaultSyncMergeMode()
                )

                const mergeService = new PersonMergeService(context)

                // Call the private mergeDistinctIds method (we'll need to make it accessible for testing)
                // For now, let's test through the public handleIdentifyOrAlias method
                ;(context as any).anonDistinctId = existingDistinctId
                const result = await mergeService.handleIdentifyOrAlias()
                expect(result.success).toBe(true)
                if (!result.success) {
                    throw new Error('Expected successful merge result')
                }
                const mergedPerson = result.person
                await result.kafkaAck

                // Flush any pending operations
                await personsStore.flush()

                // Verify the merge was successful
                expect(mergedPerson).toBeDefined()
                expect(mergedPerson?.id).toBe(existingPerson.id)

                // Verify both distinct IDs now point to the same person
                const personFromExisting = await dualWriteRepository.fetchPerson(teamId, existingDistinctId)
                const personFromNew = await dualWriteRepository.fetchPerson(teamId, newDistinctId)

                expect(personFromExisting).toBeDefined()
                expect(personFromNew).toBeDefined()
                expect(personFromExisting?.id).toBe(personFromNew?.id)
                expect(personFromExisting?.id).toBe(existingPerson.id)

                // Verify data consistency across both databases
                const primaryDids = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                    [existingPerson.id],
                    'verify-primary-dids'
                )
                const secondaryDids = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                    [teamId, existingPerson.uuid],
                    'verify-secondary-dids'
                )

                const expectedDids = [existingDistinctId, newDistinctId].sort()
                expect(primaryDids.rows.map((r: any) => r.distinct_id)).toEqual(expectedDids)
                expect(secondaryDids.rows.map((r: any) => r.distinct_id)).toEqual(expectedDids)
            })
        })

        describe('mergeDistinctIds-NeitherExist: neither distinct ID has a person', () => {
            it('creates a new person and adds both distinct IDs atomically using PersonMergeService', async () => {
                // This test validates the PersonMergeService.mergeDistinctIds behavior
                // when neither distinct ID has an existing person yet.
                // This happens during $identify events when both IDs are new.

                const firstDistinctId = 'new-user-1-neither'
                const secondDistinctId = 'new-user-2-neither'

                // Verify neither distinct ID has a person yet
                const person1Before = await dualWriteRepository.fetchPerson(teamId, firstDistinctId)
                const person2Before = await dualWriteRepository.fetchPerson(teamId, secondDistinctId)
                expect(person1Before).toBeUndefined()
                expect(person2Before).toBeUndefined()

                // Create PersonMergeService context for this scenario
                const personsStore = new BatchWritingPersonsStoreForBatch(dualWriteRepository, hub.db.kafkaProducer)

                const mergeEvent: PluginEvent = {
                    team_id: teamId,
                    distinct_id: firstDistinctId,
                    properties: {
                        $anon_distinct_id: secondDistinctId,
                        $set: { source: 'neither-exist-test' },
                    },
                    timestamp: timestamp.toISO(),
                    now: timestamp.toISO(),
                    event: '$identify',
                    uuid: new UUIDT().toString(),
                    ip: '',
                    site_url: '',
                } as PluginEvent

                const context = new PersonContext(
                    mergeEvent,
                    mainTeam,
                    firstDistinctId,
                    timestamp,
                    true, // processPerson
                    hub.db.kafkaProducer,
                    personsStore,
                    0, // deferredUpdatesStep
                    createDefaultSyncMergeMode()
                )

                const mergeService = new PersonMergeService(context)

                // Set up the context for merging
                ;(context as any).anonDistinctId = secondDistinctId

                // Execute the merge - this should create a new person with both distinct IDs
                const result = await mergeService.handleIdentifyOrAlias()
                expect(result.success).toBe(true)
                if (!result.success) {
                    throw new Error('Expected successful merge result')
                }
                const mergedPerson = result.person
                await result.kafkaAck

                // Flush any pending operations
                await personsStore.flush()

                // Verify a new person was created
                expect(mergedPerson).toBeDefined()
                expect(mergedPerson?.properties.source).toBe('neither-exist-test')
                expect(mergedPerson?.properties.$creator_event_uuid).toBeDefined()

                // Verify both distinct IDs now point to the same person
                const person1After = await dualWriteRepository.fetchPerson(teamId, firstDistinctId)
                const person2After = await dualWriteRepository.fetchPerson(teamId, secondDistinctId)

                expect(person1After).toBeDefined()
                expect(person2After).toBeDefined()
                expect(person1After?.id).toBe(person2After?.id)
                expect(person1After?.id).toBe(mergedPerson?.id)

                // Verify the person exists in both databases
                const primaryPerson = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT * FROM posthog_person WHERE id = $1',
                    [mergedPerson?.id],
                    'verify-primary-person-neither'
                )
                const secondaryPerson = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT * FROM posthog_person WHERE uuid = $1',
                    [mergedPerson?.uuid],
                    'verify-secondary-person-neither'
                )

                expect(primaryPerson.rows.length).toBe(1)
                expect(secondaryPerson.rows.length).toBe(1)
                // PersonMergeService adds $creator_event_uuid when creating a new person
                expect(primaryPerson.rows[0].properties.source).toBe('neither-exist-test')
                expect(primaryPerson.rows[0].properties.$creator_event_uuid).toBeDefined()
                expect(secondaryPerson.rows[0].properties.source).toBe('neither-exist-test')
                expect(secondaryPerson.rows[0].properties.$creator_event_uuid).toBeDefined()
                expect(primaryPerson.rows[0].properties).toEqual(secondaryPerson.rows[0].properties)

                // Verify both distinct IDs are in both databases
                const primaryDids = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                    [mergedPerson?.id],
                    'verify-primary-dids-neither'
                )
                const secondaryDids = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                    [teamId, mergedPerson?.uuid],
                    'verify-secondary-dids-neither'
                )

                const expectedDids = [firstDistinctId, secondDistinctId].sort()
                expect(primaryDids.rows.map((r: any) => r.distinct_id)).toEqual(expectedDids)
                expect(secondaryDids.rows.map((r: any) => r.distinct_id)).toEqual(expectedDids)
            })
        })

        describe('mergePeople: both distinct IDs have different persons', () => {
            it('merges two existing persons atomically with all their distinct IDs using PersonMergeService', async () => {
                // This test validates the most complex merge scenario where both distinct IDs
                // already have different persons. This requires:
                // 1. Moving all distinct IDs from source person to target person
                // 2. Updating the target person's properties
                // 3. Deleting the source person
                // 4. Updating cohorts and feature flags
                // All within a single transaction to ensure atomicity

                const person1DistinctId = 'person1-main'
                const person1ExtraId = 'person1-extra'
                const person2DistinctId = 'person2-main'
                const person2ExtraId = 'person2-extra'

                // Create first person with multiple distinct IDs
                const person1Result = await dualWriteRepository.createPerson(
                    timestamp,
                    { name: 'Person 1', status: 'active', age: 25 },
                    {},
                    {},
                    teamId,
                    null,
                    true, // is_identified
                    uuidFromDistinctId(teamId, person1DistinctId),
                    [{ distinctId: person1DistinctId, version: 0 }]
                )
                expect(person1Result.success).toBe(true)
                if (!person1Result.success) {
                    throw new Error('Expected person creation to succeed')
                }
                const person1 = person1Result.person

                // Add extra distinct ID to person1
                await dualWriteRepository.addDistinctId(person1, person1ExtraId, 0)

                // Create second person with multiple distinct IDs
                const person2Result = await dualWriteRepository.createPerson(
                    timestamp.plus({ minutes: 1 }), // Created later
                    { name: 'Person 2', email: 'person2@test.com', age: 30 },
                    {},
                    {},
                    teamId,
                    null,
                    false, // not identified
                    uuidFromDistinctId(teamId, person2DistinctId),
                    [{ distinctId: person2DistinctId, version: 0 }]
                )
                expect(person2Result.success).toBe(true)
                if (!person2Result.success) {
                    throw new Error('Expected person creation to succeed')
                }
                const person2 = person2Result.person

                // Add extra distinct ID to person2
                await dualWriteRepository.addDistinctId(person2, person2ExtraId, 0)

                // Now perform the merge using PersonMergeService
                const personsStore = new BatchWritingPersonsStoreForBatch(dualWriteRepository, hub.db.kafkaProducer)

                // The merge event would have person2's distinct ID identifying with person1's
                const mergeEvent: PluginEvent = {
                    team_id: teamId,
                    distinct_id: person1DistinctId,
                    properties: {
                        $anon_distinct_id: person2DistinctId,
                        $set: { merged: true },
                    },
                    timestamp: timestamp.plus({ minutes: 2 }).toISO(),
                    now: timestamp.plus({ minutes: 2 }).toISO(),
                    event: '$identify',
                    uuid: new UUIDT().toString(),
                    ip: '',
                    site_url: '',
                } as PluginEvent

                const context = new PersonContext(
                    mergeEvent,
                    mainTeam,
                    person1DistinctId,
                    timestamp.plus({ minutes: 2 }),
                    true, // processPerson
                    hub.db.kafkaProducer,
                    personsStore,
                    0, // deferredUpdatesStep
                    createDefaultSyncMergeMode()
                )

                const mergeService = new PersonMergeService(context)

                // Set up the context for merging two existing persons
                ;(context as any).anonDistinctId = person2DistinctId

                // Execute the merge
                const result = await mergeService.handleIdentifyOrAlias()
                expect(result.success).toBe(true)
                if (!result.success) {
                    throw new Error('Expected successful merge result')
                }
                const mergedPerson = result.person
                await result.kafkaAck

                // Flush any pending operations
                await personsStore.flush()

                // Verify the merge result
                expect(mergedPerson).toBeDefined()
                // Person1 was created first, so it should be the target
                expect(mergedPerson?.id).toBe(person1.id)
                // Properties are merged - person1's properties are kept, person2's new properties are added
                // The merge adds new properties but doesn't override existing ones
                expect(mergedPerson?.properties.name).toBe('Person 1') // person1's name is kept
                expect(mergedPerson?.properties.status).toBe('active') // person1's status is kept
                expect(mergedPerson?.properties.email).toBe('person2@test.com') // person2's email is added
                expect(mergedPerson?.properties.age).toBe(25) // person1's age is kept
                expect(mergedPerson?.properties.merged).toBe(true) // new property from event
                expect(mergedPerson?.is_identified).toBe(true) // Should be identified after merge

                // Verify all distinct IDs now point to person1
                const distinctIds = [person1DistinctId, person1ExtraId, person2DistinctId, person2ExtraId]
                for (const did of distinctIds) {
                    const person = await dualWriteRepository.fetchPerson(teamId, did)
                    expect(person).toBeDefined()
                    expect(person?.id).toBe(person1.id)
                }

                // Verify person2 was deleted
                const deletedPerson = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT * FROM posthog_person WHERE id = $1',
                    [person2.id],
                    'check-deleted-person'
                )
                expect(deletedPerson.rows.length).toBe(0)

                // Verify consistency across both databases
                const primaryDids = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                    [person1.id],
                    'verify-primary-all-dids'
                )
                const secondaryDids = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                    [teamId, person1.uuid],
                    'verify-secondary-all-dids'
                )

                expect(primaryDids.rows.map((r: any) => r.distinct_id).sort()).toEqual(distinctIds.sort())
                expect(secondaryDids.rows.map((r: any) => r.distinct_id).sort()).toEqual(distinctIds.sort())

                // Verify the merged person's properties are consistent
                const primaryPerson = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT * FROM posthog_person WHERE id = $1',
                    [person1.id],
                    'verify-primary-merged-person'
                )
                const secondaryPerson = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT * FROM posthog_person WHERE uuid = $1',
                    [person1.uuid],
                    'verify-secondary-merged-person'
                )

                expect(primaryPerson.rows.length).toBe(1)
                expect(secondaryPerson.rows.length).toBe(1)
                expect(primaryPerson.rows[0].is_identified).toBe(true)
                expect(secondaryPerson.rows[0].is_identified).toBe(true)
            })
        })

        describe('Rollback behavior on transaction failures', () => {
            it('rolls back entire merge operation when moveDistinctIds fails in dual-write', async () => {
                // This test validates that when any operation within the complex merge transaction fails,
                // the entire operation is rolled back atomically across both databases

                const person1Id = 'rollback-person1'
                const person2Id = 'rollback-person2'

                // Create two persons
                const person1Result = await dualWriteRepository.createPerson(
                    timestamp,
                    { name: 'Rollback Person 1' },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuidFromDistinctId(teamId, person1Id),
                    [{ distinctId: person1Id, version: 0 }]
                )

                const person2Result = await dualWriteRepository.createPerson(
                    timestamp.plus({ minutes: 1 }),
                    { name: 'Rollback Person 2' },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuidFromDistinctId(teamId, person2Id),
                    [{ distinctId: person2Id, version: 0 }]
                )

                expect(person1Result.success).toBe(true)
                expect(person2Result.success).toBe(true)
                if (!person1Result.success || !person2Result.success) {
                    throw new Error('Expected person creations to succeed')
                }
                const person1 = person1Result.person
                const person2 = person2Result.person

                // Mock the secondary repository to fail during moveDistinctIds
                // Need to fail 3 times to exhaust the default retry count
                const spy = jest.spyOn((dualWriteRepository as any).secondaryRepo, 'moveDistinctIds')
                spy.mockRejectedValueOnce(new Error('Simulated secondary database failure - attempt 1'))
                    .mockRejectedValueOnce(new Error('Simulated secondary database failure - attempt 2'))
                    .mockRejectedValueOnce(new Error('Simulated secondary database failure - attempt 3'))

                // Attempt the merge which should fail and rollback
                const personsStore = new BatchWritingPersonsStoreForBatch(dualWriteRepository, hub.db.kafkaProducer)

                const mergeEvent: PluginEvent = {
                    team_id: teamId,
                    distinct_id: person1Id,
                    properties: {
                        $anon_distinct_id: person2Id,
                    },
                    timestamp: timestamp.plus({ minutes: 2 }).toISO(),
                    now: timestamp.plus({ minutes: 2 }).toISO(),
                    event: '$identify',
                    uuid: new UUIDT().toString(),
                    ip: '',
                    site_url: '',
                } as PluginEvent

                const context = new PersonContext(
                    mergeEvent,
                    mainTeam,
                    person1Id,
                    timestamp.plus({ minutes: 2 }),
                    true,
                    hub.db.kafkaProducer,
                    personsStore,
                    0,
                    createDefaultSyncMergeMode()
                )

                const mergeService = new PersonMergeService(context)
                ;(context as any).anonDistinctId = person2Id

                // The merge should fail internally but PersonMergeService catches errors
                // We need to check that the operation didn't succeed
                try {
                    const result = await mergeService.handleIdentifyOrAlias()
                    if (result.success) {
                        await result.kafkaAck
                    }
                    await personsStore.flush()
                } catch (e: any) {
                    // Expected to catch error
                }

                spy.mockRestore()

                // After exhausting retries, the merge should have failed
                // PersonMergeService catches the error and returns undefined

                // Verify nothing changed - both persons should still exist independently
                const person1After = await dualWriteRepository.fetchPerson(teamId, person1Id)
                const person2After = await dualWriteRepository.fetchPerson(teamId, person2Id)

                expect(person1After).toBeDefined()
                expect(person2After).toBeDefined()
                expect(person1After?.id).toBe(person1.id)
                expect(person2After?.id).toBe(person2.id)
                expect(person1After?.id).not.toBe(person2After?.id)

                // Verify distinct IDs are still with their original persons
                const primaryPerson1Dids = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1',
                    [person1.id],
                    'verify-rollback-person1-dids'
                )
                const primaryPerson2Dids = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1',
                    [person2.id],
                    'verify-rollback-person2-dids'
                )

                expect(primaryPerson1Dids.rows.map((r: any) => r.distinct_id)).toEqual([person1Id])
                expect(primaryPerson2Dids.rows.map((r: any) => r.distinct_id)).toEqual([person2Id])

                // Verify both persons still exist in both databases
                const secondaryPerson1 = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT * FROM posthog_person WHERE uuid = $1',
                    [person1.uuid],
                    'verify-secondary-person1-exists'
                )
                const secondaryPerson2 = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT * FROM posthog_person WHERE uuid = $1',
                    [person2.uuid],
                    'verify-secondary-person2-exists'
                )

                expect(secondaryPerson1.rows.length).toBe(1)
                expect(secondaryPerson2.rows.length).toBe(1)
            })

            it('rolls back when database constraint violation occurs during merge', async () => {
                // This test validates rollback behavior when a database constraint is violated
                // (e.g., unique constraint on distinct_id)

                const existingId = 'constraint-existing'
                const newPersonId = 'constraint-new'

                // Create an existing person
                const existingResult = await dualWriteRepository.createPerson(
                    timestamp,
                    { name: 'Existing for Constraint Test' },
                    {},
                    {},
                    teamId,
                    null,
                    false,
                    uuidFromDistinctId(teamId, existingId),
                    [{ distinctId: existingId, version: 0 }]
                )

                expect(existingResult.success).toBe(true)
                if (!existingResult.success) {
                    throw new Error('Expected person creation to succeed')
                }
                const existingPerson = existingResult.person

                // Mock to simulate a constraint violation when adding distinct ID
                // Need to fail 3 times to exhaust the default retry count
                const spy = jest.spyOn((dualWriteRepository as any).primaryRepo, 'addDistinctId')
                spy.mockRejectedValueOnce(new Error('duplicate key value violates unique constraint - attempt 1'))
                    .mockRejectedValueOnce(new Error('duplicate key value violates unique constraint - attempt 2'))
                    .mockRejectedValueOnce(new Error('duplicate key value violates unique constraint - attempt 3'))

                // Try to merge with a new distinct ID
                const personsStore = new BatchWritingPersonsStoreForBatch(dualWriteRepository, hub.db.kafkaProducer)

                const mergeEvent: PluginEvent = {
                    team_id: teamId,
                    distinct_id: newPersonId,
                    properties: {
                        $anon_distinct_id: existingId,
                        $set: { should_not_persist: true },
                    },
                    timestamp: timestamp.toISO(),
                    now: timestamp.toISO(),
                    event: '$identify',
                    uuid: new UUIDT().toString(),
                    ip: '',
                    site_url: '',
                } as PluginEvent

                const context = new PersonContext(
                    mergeEvent,
                    mainTeam,
                    newPersonId,
                    timestamp,
                    true,
                    hub.db.kafkaProducer,
                    personsStore,
                    0,
                    createDefaultSyncMergeMode()
                )

                const mergeService = new PersonMergeService(context)
                ;(context as any).anonDistinctId = existingId

                // The operation should fail internally
                try {
                    const result = await mergeService.handleIdentifyOrAlias()
                    if (result.success) {
                        await result.kafkaAck
                    }
                    await personsStore.flush()
                } catch (e: any) {
                    // Expected to catch error
                }

                spy.mockRestore()

                // Verify the existing person is unchanged
                const personAfter = await dualWriteRepository.fetchPerson(teamId, existingId)
                expect(personAfter).toBeDefined()
                expect(personAfter?.id).toBe(existingPerson.id)
                expect(personAfter?.properties).toEqual({ name: 'Existing for Constraint Test' })
                expect(personAfter?.properties.should_not_persist).toBeUndefined()

                // Verify the new distinct ID was not added
                const person2 = await dualWriteRepository.fetchPerson(teamId, newPersonId)
                expect(person2).toBeUndefined()

                // Verify consistency across databases
                const primaryDids = await hub.db.postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1',
                    [existingPerson.id],
                    'verify-constraint-primary-dids'
                )
                const secondaryDids = await hub.db.postgresPersonMigration.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2)',
                    [teamId, existingPerson.uuid],
                    'verify-constraint-secondary-dids'
                )

                expect(primaryDids.rows.map((r: any) => r.distinct_id)).toEqual([existingId])
                expect(secondaryDids.rows.map((r: any) => r.distinct_id)).toEqual([existingId])
            })
        })
    })
})
