import fs from 'fs'
import { DateTime } from 'luxon'
import path from 'path'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'
import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, InternalPerson, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'
import { UUIDT } from '~/utils/utils'
import { uuidFromDistinctId } from '~/worker/ingestion/person-uuid'
import { BatchWritingPersonsStoreForBatch } from '~/worker/ingestion/persons/batch-writing-person-store'
import { PersonContext } from '~/worker/ingestion/persons/person-context'
import { PersonCreateService } from '~/worker/ingestion/persons/person-create-service'
import { PersonMergeService } from '~/worker/ingestion/persons/person-merge-service'
import { PostgresDualWritePersonRepository } from '~/worker/ingestion/persons/repositories/postgres-dualwrite-person-repository'

import { PersonsStoreForBatch } from '../../../src/worker/ingestion/persons/persons-store-for-batch'

jest.setTimeout(30000)
jest.mock('~/utils/logger')

describe('DualWrite Person ingestion integration', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let repository: PostgresDualWritePersonRepository
    let mockProducerObserver: KafkaProducerObserver

    async function setupMigrationDb(): Promise<void> {
        // reset persons schema on secondary and ensure primary also has it
        const drops = [
            'posthog_featureflaghashkeyoverride',
            'posthog_cohortpeople',
            'posthog_persondistinctid',
            'posthog_personlessdistinctid',
            'posthog_person',
        ]
        for (const table of drops) {
            // Drop on secondary (migration) DB
            await migrationPostgres.query(
                PostgresUse.PERSONS_WRITE,
                `DROP TABLE IF EXISTS ${table} CASCADE`,
                [],
                `drop-${table}`
            )
            // Ensure primary Persons schema is also reset to our minimal schema (avoid legacy FKs)
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `DROP TABLE IF EXISTS ${table} CASCADE`,
                [],
                `drop-primary-${table}`
            )
        }
        const sqlPath = path.resolve(__dirname, '../../../sql/create_persons_tables.sql')
        const sql = fs.readFileSync(sqlPath, 'utf8')
        await migrationPostgres.query(PostgresUse.PERSONS_WRITE, sql, [], 'create-persons-schema-secondary')
        await postgres.query(PostgresUse.PERSONS_WRITE, sql, [], 'create-persons-schema-primary')
    }

    async function cleanupPrepared(hub: Hub) {
        const routers = [hub.db.postgres, hub.db.postgresPersonMigration]
        for (const r of routers) {
            const res = await r.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT gid FROM pg_prepared_xacts WHERE gid LIKE 'dualwrite:%'`,
                [],
                'list-prepared'
            )
            for (const row of res.rows) {
                await r.query(
                    PostgresUse.PERSONS_WRITE,
                    `ROLLBACK PREPARED '${String(row.gid).replace(/'/g, "''")}'`,
                    [],
                    'rollback-prepared'
                )
            }
        }
    }

    async function getFirstTeam(hub: Hub): Promise<Team> {
        const teams = await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            'SELECT * FROM posthog_team LIMIT 1',
            [],
            'getFirstTeam'
        )
        return teams.rows[0]
    }

    function personMergeServiceDual(
        {
            team,
            distinctId,
            event,
            timestamp,
            properties,
        }: {
            team: Team
            distinctId: string
            event: '$identify' | '$create_alias' | '$merge_dangerously'
            timestamp: DateTime
            properties: Record<string, any>
        },
        customRepo?: PostgresDualWritePersonRepository
    ) {
        const personsStore = new BatchWritingPersonsStoreForBatch(customRepo ?? repository, hub.db.kafkaProducer)
        const context = new PersonContext(
            {
                team_id: team.id,
                event,
                distinct_id: distinctId,
                uuid: new UUIDT().toString(),
                properties,
            } as any,
            team,
            distinctId,
            timestamp,
            true,
            hub.db.kafkaProducer,
            personsStore,
            0
        )
        return new PersonMergeService(context)
    }

    async function flushPersonStoreToKafka(hub: Hub, personStore: PersonsStoreForBatch, kafkaAcks: Promise<void>) {
        const kafkaMessages = await personStore.flush()
        await hub.db.kafkaProducer.queueMessages(kafkaMessages.map((message) => message.topicMessage))
        await hub.db.kafkaProducer.flush()
        await kafkaAcks
        return kafkaMessages
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        migrationPostgres = hub.db.postgresPersonMigration
        await setupMigrationDb()

        repository = new PostgresDualWritePersonRepository(postgres, migrationPostgres)
        mockProducerObserver = new KafkaProducerObserver(hub.kafkaProducer)
        mockProducerObserver.resetKafkaProducer()

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)
    })

    afterEach(async () => {
        await cleanupPrepared(hub)
        await closeHub(hub)
        jest.clearAllMocks()
        jest.restoreAllMocks()
    })

    describe('Person Creation via PersonCreateService', () => {
        function createPersonCreateService(team: Team, distinctId: string) {
            const personsStore = new BatchWritingPersonsStoreForBatch(repository, hub.db.kafkaProducer)
            const context = new PersonContext(
                {
                    team_id: team.id,
                    event: '$pageview',
                    distinct_id: distinctId,
                    uuid: new UUIDT().toString(),
                    properties: {},
                } as any,
                team,
                distinctId,
                DateTime.now(),
                true,
                hub.db.kafkaProducer,
                personsStore,
                0
            )
            return { service: new PersonCreateService(context), context }
        }

        it('creates a person with dual write when called via service', async () => {
            const team = await getFirstTeam(hub)
            const createdAt = DateTime.fromISO('2024-02-03T10:00:00.000Z').toUTC()
            const distinctId = 'service-create-1'
            const { service, context } = createPersonCreateService(team, distinctId)

            const [person, wasCreated] = await service.createPerson(
                createdAt,
                { name: 'Service User' },
                { initial_prop: 'once' },
                team.id,
                null,
                false,
                'event-uuid-1',
                [{ distinctId, version: 0 }]
            )

            expect(wasCreated).toBe(true)
            expect(person.properties).toMatchObject({
                name: 'Service User',
                initial_prop: 'once',
                $creator_event_uuid: 'event-uuid-1',
            })

            // Verify person exists in both DBs
            const primaryPerson = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, person.uuid],
                'verify-primary-service-create'
            )
            const secondaryPerson = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, person.uuid],
                'verify-secondary-service-create'
            )

            expect(primaryPerson.rows.length).toBe(1)
            expect(secondaryPerson.rows.length).toBe(1)
            expect(primaryPerson.rows[0].properties).toEqual(secondaryPerson.rows[0].properties)

            // Verify distinct ID exists in both DBs
            const primaryDistinct = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, distinctId],
                'verify-primary-service-distinct'
            )
            const secondaryDistinct = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, distinctId],
                'verify-secondary-service-distinct'
            )

            expect(primaryDistinct.rows.length).toBe(1)
            expect(secondaryDistinct.rows.length).toBe(1)

            // Flush store to Kafka
            await flushPersonStoreToKafka(hub, context.personStore, Promise.resolve())
        })

        it('handles creation conflicts across both DBs', async () => {
            const team = await getFirstTeam(hub)
            const createdAt = DateTime.fromISO('2024-02-03T11:00:00.000Z').toUTC()
            const distinctId = 'service-conflict-1'
            const uuid = uuidFromDistinctId(team.id, distinctId)

            // Pre-create person directly via repository
            const preCreateResult = await repository.createPerson(
                createdAt,
                { existing: true },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId, version: 0 }]
            )
            expect(preCreateResult.success).toBe(true)

            const { service, context } = createPersonCreateService(team, distinctId)

            // Try to create same person via service - should handle conflict gracefully
            // Use a different distinctId to avoid UUID collision, but same person should be found
            const [person, wasCreated] = await service.createPerson(
                createdAt,
                { name: 'Conflict User' },
                {},
                team.id,
                null,
                false,
                'event-uuid-2',
                [{ distinctId: 'service-conflict-1-alt', version: 0 }] // Different distinct ID
            )

            expect(wasCreated).toBe(true) // This will create a new person since distinctId is different
            expect(person.uuid).not.toBe(uuid) // Different UUID since different distinctId

            // Verify two persons exist in both DBs (original + new one)
            const primaryCount = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                [team.id],
                'verify-primary-conflict-count'
            )
            const secondaryCount = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                [team.id],
                'verify-secondary-conflict-count'
            )

            expect(Number(primaryCount.rows[0].count)).toBe(2)
            expect(Number(secondaryCount.rows[0].count)).toBe(2)

            await flushPersonStoreToKafka(hub, context.personStore, Promise.resolve())
        })

        it('rolls back on secondary failure during service create', async () => {
            const team = await getFirstTeam(hub)
            const createdAt = DateTime.fromISO('2024-02-03T12:00:00.000Z').toUTC()
            const distinctId = 'service-rollback-1'

            // Mock secondary to fail during createPerson
            const originalQuery = migrationPostgres.query.bind(migrationPostgres)
            jest.spyOn(migrationPostgres, 'query').mockImplementation(async (use, query, params, tag) => {
                const queryString = typeof query === 'string' ? query : query.text
                const queryTag = typeof tag === 'string' ? tag : ''

                if (queryString.includes('INSERT INTO posthog_person') && queryTag.includes('insertPerson')) {
                    throw new Error('Simulated secondary failure during service create')
                }
                return originalQuery(use, query, params, tag)
            })

            const { service, context } = createPersonCreateService(team, distinctId)

            await expect(
                service.createPerson(createdAt, { name: 'Rollback User' }, {}, team.id, null, false, 'event-uuid-3', [
                    { distinctId, version: 0 },
                ])
            ).rejects.toThrow('Simulated secondary failure during service create')

            // Verify no person was created in either DB
            const primaryPersons = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                [team.id],
                'verify-primary-service-rollback'
            )
            const secondaryPersons = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                [team.id],
                'verify-secondary-service-rollback'
            )

            expect(Number(primaryPersons.rows[0].count)).toBe(0)
            expect(Number(secondaryPersons.rows[0].count)).toBe(0)

            // Verify no distinct IDs were created in either DB
            const primaryDistinct = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                [team.id],
                'verify-primary-service-distinct-rollback'
            )
            const secondaryDistinct = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                [team.id],
                'verify-secondary-service-distinct-rollback'
            )

            expect(Number(primaryDistinct.rows[0].count)).toBe(0)
            expect(Number(secondaryDistinct.rows[0].count)).toBe(0)

            await flushPersonStoreToKafka(hub, context.personStore, Promise.resolve())
        })

        it('handles large property sets (Kafka message size limits)', async () => {
            const team = await getFirstTeam(hub)
            const createdAt = DateTime.fromISO('2024-02-03T13:00:00.000Z').toUTC()
            const distinctId = 'service-size-violation-1'

            // Create very large properties that exceed Kafka message size limit
            const largeProperties: Record<string, string> = {}
            for (let i = 0; i < 2000; i++) {
                largeProperties[`large_prop_${i.toString().padStart(4, '0')}`] = 'x'.repeat(2000) // Much larger data
            }

            const { service, context } = createPersonCreateService(team, distinctId)

            let createResult: any
            let createError: any

            try {
                createResult = await service.createPerson(
                    createdAt,
                    largeProperties,
                    {},
                    team.id,
                    null,
                    false,
                    'event-uuid-4',
                    [{ distinctId, version: 0 }]
                )
            } catch (error) {
                // pass
                createError = error
            }

            // Check what actually happened - look for the specific distinctId
            const primaryPersons = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person p JOIN posthog_persondistinctid pd ON p.id = pd.person_id WHERE p.team_id = $1 AND pd.distinct_id = $2',
                [team.id, distinctId],
                'verify-primary-service-size-violation'
            )
            const secondaryPersons = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person p JOIN posthog_persondistinctid pd ON p.id = pd.person_id WHERE p.team_id = $1 AND pd.distinct_id = $2',
                [team.id, distinctId],
                'verify-secondary-service-size-violation'
            )

            const primaryCount = Number(primaryPersons.rows[0].count)
            const secondaryCount = Number(secondaryPersons.rows[0].count)

            if (createError) {
                if (createError.message.includes('Message size too large')) {
                    // Kafka message size error - person should be created in DB but Kafka message failed
                    expect(primaryCount).toBe(1)
                    expect(secondaryCount).toBe(1)
                    expect(createError.name).toBe('MessageSizeTooLarge')
                } else if (createError.message.match(/size|limit|properties|violation/i)) {
                    // Database property size violation - no person should be created
                    expect(primaryCount).toBe(0)
                    expect(secondaryCount).toBe(0)
                } else {
                    // Some other error - re-throw to see what it is
                    throw createError
                }
            } else {
                // If no error was thrown, person should be created successfully
                expect(createResult).toBeDefined()
                expect(createResult[1]).toBe(true) // wasCreated
                expect(primaryCount).toBe(1)
                expect(secondaryCount).toBe(1)
            }

            await flushPersonStoreToKafka(hub, context.personStore, Promise.resolve())
        })
    })

    describe('Person Merging via PersonMergeService', () => {
        describe('$identify events', () => {
            describe('OneExists scenario', () => {
                it('adds distinct ID to existing person (happy path)', async () => {
                    const team = await getFirstTeam(hub)
                    const timestamp = DateTime.fromISO('2024-02-04T10:00:00.000Z').toUTC()
                    const existingDistinctId = 'existing-one-1'
                    const newDistinctId = 'new-one-1'

                    // Create existing person
                    const existingResult = await repository.createPerson(
                        timestamp,
                        { name: 'Existing User' },
                        {},
                        {},
                        team.id,
                        null,
                        true,
                        uuidFromDistinctId(team.id, existingDistinctId),
                        [{ distinctId: existingDistinctId, version: 0 }]
                    )
                    expect(existingResult.success).toBe(true)

                    // Perform $identify: newDistinctId identifies with existingDistinctId
                    const mergeService = personMergeServiceDual({
                        team,
                        distinctId: newDistinctId,
                        event: '$identify',
                        timestamp,
                        properties: { $anon_distinct_id: existingDistinctId },
                    })

                    const [person, acks] = await mergeService.handleIdentifyOrAlias()
                    expect(person).toBeDefined()
                    await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                    // Verify both distinct IDs point to same person in both DBs
                    const primaryDistincts = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                        [person!.id],
                        'verify-primary-one-exists-distincts'
                    )
                    const secondaryDistincts = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                        [team.id, person!.uuid],
                        'verify-secondary-one-exists-distincts'
                    )

                    const primaryIds = primaryDistincts.rows.map((r) => r.distinct_id).sort()
                    const secondaryIds = secondaryDistincts.rows.map((r) => r.distinct_id).sort()

                    expect(primaryIds).toEqual([existingDistinctId, newDistinctId])
                    expect(secondaryIds).toEqual([existingDistinctId, newDistinctId])
                })

                it('correctly sets version based on personless state', async () => {
                    const team = await getFirstTeam(hub)
                    const timestamp = DateTime.fromISO('2024-02-04T11:00:00.000Z').toUTC()
                    const existingDistinctId = 'existing-one-2'
                    const newDistinctId = 'personless-one-2'

                    // Create existing person
                    await repository.createPerson(
                        timestamp,
                        { name: 'Existing User 2' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuidFromDistinctId(team.id, existingDistinctId),
                        [{ distinctId: existingDistinctId, version: 0 }]
                    )

                    // Mark new distinct ID as used in personless mode
                    await repository.addPersonlessDistinctId(team.id, newDistinctId)

                    // Perform $identify: newDistinctId identifies with existingDistinctId
                    const mergeService = personMergeServiceDual({
                        team,
                        distinctId: newDistinctId,
                        event: '$identify',
                        timestamp,
                        properties: { $anon_distinct_id: existingDistinctId },
                    })

                    const [person, acks] = await mergeService.handleIdentifyOrAlias()
                    expect(person).toBeDefined()
                    await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                    // Verify the new distinct ID got version 1 (because it was personless)
                    const primaryVersion = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT version FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                        [newDistinctId, team.id],
                        'verify-primary-personless-version'
                    )
                    const secondaryVersion = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT version FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                        [newDistinctId, team.id],
                        'verify-secondary-personless-version'
                    )

                    expect(Number(primaryVersion.rows[0].version)).toBe(1)
                    expect(Number(secondaryVersion.rows[0].version)).toBe(1)
                })
            })

            describe('NeitherExist scenario', () => {
                it('creates person with both distinct IDs (happy path)', async () => {
                    const team = await getFirstTeam(hub)
                    const timestamp = DateTime.fromISO('2024-02-04T14:00:00.000Z').toUTC()
                    const anonDistinctId = 'anon-user-1'
                    const identifiedDistinctId = 'identified-user-1'

                    const mergeService = personMergeServiceDual({
                        team,
                        distinctId: identifiedDistinctId,
                        event: '$identify',
                        timestamp,
                        properties: { $anon_distinct_id: anonDistinctId },
                    })

                    const [person, acks] = await mergeService.handleIdentifyOrAlias()
                    expect(person).toBeDefined()
                    await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                    // Verify person created with both distinct IDs in both DBs
                    const primaryDistincts = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                        [person!.id],
                        'verify-primary-neither-exists-distincts'
                    )
                    const secondaryDistincts = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                        [team.id, person!.uuid],
                        'verify-secondary-neither-exists-distincts'
                    )

                    const primaryIds = primaryDistincts.rows.map((r) => r.distinct_id).sort()
                    const secondaryIds = secondaryDistincts.rows.map((r) => r.distinct_id).sort()

                    expect(primaryIds).toEqual([anonDistinctId, identifiedDistinctId])
                    expect(secondaryIds).toEqual([anonDistinctId, identifiedDistinctId])
                    expect(person!.is_identified).toBe(true)
                })

                it('optimizes version selection when both are new', async () => {
                    const team = await getFirstTeam(hub)
                    const timestamp = DateTime.fromISO('2024-02-04T15:00:00.000Z').toUTC()
                    const anonDistinctId = 'anon-user-2'
                    const identifiedDistinctId = 'identified-user-2'

                    const mergeService = personMergeServiceDual({
                        team,
                        distinctId: identifiedDistinctId,
                        event: '$identify',
                        timestamp,
                        properties: { $anon_distinct_id: anonDistinctId },
                    })

                    const [person, acks] = await mergeService.handleIdentifyOrAlias()
                    expect(person).toBeDefined()
                    await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                    // Both distinct IDs should get version 0 since they're new
                    const primaryVersions = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT distinct_id, version FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                        [person!.id],
                        'verify-primary-neither-versions'
                    )
                    const secondaryVersions = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT distinct_id, version FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                        [team.id, person!.uuid],
                        'verify-secondary-neither-versions'
                    )

                    expect(primaryVersions.rows).toHaveLength(2)
                    expect(secondaryVersions.rows).toHaveLength(2)

                    primaryVersions.rows.forEach((row) => expect(Number(row.version)).toBe(0))
                    secondaryVersions.rows.forEach((row) => expect(Number(row.version)).toBe(0))
                })
                it('rolls back when secondary createPerson fails', async () => {
                    const team = await getFirstTeam(hub)
                    const timestamp = DateTime.fromISO('2024-02-05T12:00:00.000Z').toUTC()
                    const anonDistinctId = 'anon-user-rollback'
                    const identifiedDistinctId = 'identified-user-rollback'

                    // Force secondary failure during createPerson inside the 2PC transaction
                    const spy = jest
                        .spyOn((repository as any).secondaryRepo, 'createPerson')
                        .mockRejectedValue(new Error('simulated secondary create failure'))

                    const mergeService = personMergeServiceDual({
                        team,
                        distinctId: identifiedDistinctId,
                        event: '$identify',
                        timestamp,
                        properties: { $anon_distinct_id: anonDistinctId },
                    })

                    const [maybePerson, acks] = await mergeService.handleIdentifyOrAlias()
                    expect(maybePerson).toBeUndefined()
                    await expect(acks).resolves.toBeUndefined()

                    spy.mockRestore()

                    // Verify both sides rolled back completely
                    const primaryPdi = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = ANY($2::text[])',
                        [team.id, [anonDistinctId, identifiedDistinctId]],
                        'verify-primary-create-rolled-back'
                    )
                    const secondaryPdi = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = ANY($2::text[])',
                        [team.id, [anonDistinctId, identifiedDistinctId]],
                        'verify-secondary-create-rolled-back'
                    )

                    const primaryPersonless = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = ANY($2::text[])',
                        [team.id, [anonDistinctId, identifiedDistinctId]],
                        'verify-primary-personless-rolled-back'
                    )
                    const secondaryPersonless = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = ANY($2::text[])',
                        [team.id, [anonDistinctId, identifiedDistinctId]],
                        'verify-secondary-personless-rolled-back'
                    )

                    // Verify no person rows created on either side for potential UUIDs
                    const pPerson1 = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, uuidFromDistinctId(team.id, identifiedDistinctId)],
                        'verify-primary-person-rolled-back-1'
                    )
                    const pPerson2 = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, uuidFromDistinctId(team.id, anonDistinctId)],
                        'verify-primary-person-rolled-back-2'
                    )
                    const sPerson1 = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, uuidFromDistinctId(team.id, identifiedDistinctId)],
                        'verify-secondary-person-rolled-back-1'
                    )
                    const sPerson2 = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, uuidFromDistinctId(team.id, anonDistinctId)],
                        'verify-secondary-person-rolled-back-2'
                    )

                    expect(primaryPdi.rows.length).toBe(0)
                    expect(secondaryPdi.rows.length).toBe(0)
                    expect(primaryPersonless.rows.length).toBe(0)
                    expect(secondaryPersonless.rows.length).toBe(0)
                    expect(pPerson1.rows.length + pPerson2.rows.length).toBe(0)
                    expect(sPerson1.rows.length + sPerson2.rows.length).toBe(0)
                })
            })

            describe('BothExist scenario (mergePeople)', () => {
                it('merges with property updates', async () => {
                    const team = await getFirstTeam(hub)

                    const tsSrc = DateTime.fromISO('2024-02-01T09:00:00.000Z').toUTC()
                    const tsTgt = DateTime.fromISO('2024-02-01T10:00:00.000Z').toUTC()
                    const tsEvent = DateTime.fromISO('2024-02-01T11:00:00.000Z').toUTC()

                    const sourceDistinct = 'merge-src'
                    const targetDistinct = 'merge-tgt'

                    const srcUuid = uuidFromDistinctId(team.id, sourceDistinct)
                    const tgtUuid = uuidFromDistinctId(team.id, targetDistinct)

                    // Create two existing persons on both DBs with overlapping properties
                    const src = await repository.createPerson(
                        tsSrc,
                        { name: 'src', a: 1, overlap: 'src' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        srcUuid,
                        [{ distinctId: sourceDistinct, version: 0 }]
                    )
                    const tgt = await repository.createPerson(
                        tsTgt,
                        { name: 'tgt', b: 2, overlap: 'tgt' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        tgtUuid,
                        [{ distinctId: targetDistinct, version: 0 }]
                    )
                    expect(src.success && tgt.success).toBe(true)

                    // Perform identify merge with property updates ($set and $set_once)
                    const svc = personMergeServiceDual({
                        team,
                        distinctId: targetDistinct,
                        event: '$identify',
                        timestamp: tsEvent,
                        properties: {
                            $anon_distinct_id: sourceDistinct,
                            $set: { setK: 'v', overlap: 'from_event' },
                            $set_once: { onceOnly: 'once' },
                        },
                    })

                    const [person, acks] = await svc.handleIdentifyOrAlias()
                    const ctx = svc.getContext()
                    await flushPersonStoreToKafka(hub, ctx.personStore, acks)

                    // Primary assertions: single surviving person with merged properties and both distinct IDs
                    const pPerson = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT id, uuid, properties, is_identified FROM posthog_person WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-primary-merge-bothexist-props'
                    )
                    expect(pPerson.rows.length).toBe(1)
                    expect(pPerson.rows[0].uuid === tgtUuid || pPerson.rows[0].uuid === srcUuid).toBe(true)
                    expect(pPerson.rows[0].is_identified).toBe(true)
                    expect(pPerson.rows[0].properties).toMatchObject({
                        // overlap should be overridden by event $set value
                        overlap: 'from_event',
                        // $set applied
                        setK: 'v',
                        // $set_once applied since it did not previously exist
                        onceOnly: 'once',
                        // carry-through of existing properties
                        a: 1,
                        b: 2,
                    })

                    const pDistinct = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                        [pPerson.rows[0].id],
                        'verify-primary-merge-bothexist-props-distinct'
                    )
                    expect(pDistinct.rows.map((r: any) => r.distinct_id).sort()).toEqual(
                        [sourceDistinct, targetDistinct].sort()
                    )

                    // Secondary assertions: identical state
                    const sPerson = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT id, uuid, properties, is_identified FROM posthog_person WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-secondary-merge-bothexist-props'
                    )
                    expect(sPerson.rows.length).toBe(1)
                    expect(sPerson.rows[0].uuid === tgtUuid || sPerson.rows[0].uuid === srcUuid).toBe(true)
                    expect(sPerson.rows[0].is_identified).toBe(true)
                    expect(sPerson.rows[0].properties).toMatchObject({
                        overlap: 'from_event',
                        setK: 'v',
                        onceOnly: 'once',
                        a: 1,
                        b: 2,
                    })

                    const sDistinct = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        `SELECT pd.distinct_id
                         FROM posthog_persondistinctid pd
                         WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2)
                         ORDER BY distinct_id`,
                        [team.id, sPerson.rows[0].uuid],
                        'verify-secondary-merge-bothexist-props-distinct'
                    )
                    expect(sDistinct.rows.map((r: any) => r.distinct_id).sort()).toEqual(
                        [sourceDistinct, targetDistinct].sort()
                    )

                    // Returned person matches the survivor and properties
                    expect(person).toMatchObject<Partial<InternalPerson>>({
                        uuid: sPerson.rows[0].uuid,
                        is_identified: true,
                        properties: expect.objectContaining({
                            overlap: 'from_event',
                            setK: 'v',
                            onceOnly: 'once',
                            a: 1,
                            b: 2,
                        }),
                    })
                })

                it('merges cohorts and feature flags', async () => {
                    const team = await getFirstTeam(hub)
                    const createdAt = DateTime.fromISO('2024-02-02T10:00:00.000Z').toUTC()

                    const sourceDistinct = 'cohort-src'
                    const targetDistinct = 'cohort-tgt'
                    const srcUuid = uuidFromDistinctId(team.id, sourceDistinct)
                    const tgtUuid = uuidFromDistinctId(team.id, targetDistinct)

                    // Create two existing persons (both DBs)
                    const src = await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, srcUuid, [
                        { distinctId: sourceDistinct, version: 0 },
                    ])
                    const tgt = await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, tgtUuid, [
                        { distinctId: targetDistinct, version: 0 },
                    ])
                    expect(src.success && tgt.success).toBe(true)
                    if (!src.success || !tgt.success) {
                        throw new Error('Failed to create test persons')
                    }

                    const srcPerson = src.person
                    const tgtPerson = tgt.person

                    // Seed cohort membership and feature flag overrides for source in both DBs
                    const seedCohortAndFlags = async (router: PostgresRouter) => {
                        // cohortpeople
                        await router.query(
                            PostgresUse.PERSONS_WRITE,
                            'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                            [1, srcPerson.id, team.id],
                            'seed-cohortpeople'
                        )
                        // featureflaghashkeyoverride
                        await router.query(
                            PostgresUse.PERSONS_WRITE,
                            'INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) VALUES ($1, $2, $3, $4)',
                            [team.id, srcPerson.id, 'flag-a', 'hash-src-a'],
                            'seed-ff-override-a'
                        )
                        await router.query(
                            PostgresUse.PERSONS_WRITE,
                            'INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) VALUES ($1, $2, $3, $4)',
                            [team.id, srcPerson.id, 'flag-b', 'hash-src-b'],
                            'seed-ff-override-b'
                        )
                    }

                    await seedCohortAndFlags(postgres)
                    await seedCohortAndFlags(migrationPostgres)

                    // Run merge via service ($identify with anon pointing to source)
                    const svc = personMergeServiceDual({
                        team,
                        distinctId: targetDistinct,
                        event: '$identify',
                        timestamp: createdAt,
                        properties: { $anon_distinct_id: sourceDistinct },
                    })

                    const [merged, acks] = await svc.handleIdentifyOrAlias()
                    const ctx = svc.getContext()
                    await flushPersonStoreToKafka(hub, ctx.personStore, acks)
                    expect(merged).toBeDefined()

                    // Primary: cohortpeople moved to target person, source overrides deleted and reinserted for target
                    const pCohort = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE person_id = $1',
                        [tgtPerson.id],
                        'verify-primary-cohort-moved'
                    )
                    expect(pCohort.rows).toEqual([{ cohort_id: 1, person_id: tgtPerson.id }])

                    const pOverrides = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT feature_flag_key, hash_key FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = $2 ORDER BY feature_flag_key',
                        [team.id, tgtPerson.id],
                        'verify-primary-ff-moved'
                    )
                    expect(pOverrides.rows).toEqual([
                        { feature_flag_key: 'flag-a', hash_key: 'hash-src-a' },
                        { feature_flag_key: 'flag-b', hash_key: 'hash-src-b' },
                    ])

                    // Ensure there are no lingering rows for source
                    const pOverridesSource = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = $2',
                        [team.id, srcPerson.id],
                        'verify-primary-ff-source-gone'
                    )
                    expect(pOverridesSource.rows.length).toBe(0)

                    // Secondary: identical checks
                    const sCohort = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE person_id = $1',
                        [tgtPerson.id],
                        'verify-secondary-cohort-moved'
                    )
                    expect(sCohort.rows).toEqual([{ cohort_id: 1, person_id: tgtPerson.id }])

                    const sOverrides = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT feature_flag_key, hash_key FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = $2 ORDER BY feature_flag_key',
                        [team.id, tgtPerson.id],
                        'verify-secondary-ff-moved'
                    )
                    expect(sOverrides.rows).toEqual([
                        { feature_flag_key: 'flag-a', hash_key: 'hash-src-a' },
                        { feature_flag_key: 'flag-b', hash_key: 'hash-src-b' },
                    ])

                    const sOverridesSource = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT 1 FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = $2',
                        [team.id, srcPerson.id],
                        'verify-secondary-ff-source-gone'
                    )
                    expect(sOverridesSource.rows.length).toBe(0)
                })

                it('rolls back on secondary failure', async () => {
                    const team = await getFirstTeam(hub)
                    const timestamp = DateTime.fromISO('2024-02-01T10:30:00.000Z').toUTC()

                    const sourceDistinct = 'rb-src'
                    const targetDistinct = 'rb-tgt'
                    const srcUuid = uuidFromDistinctId(team.id, sourceDistinct)
                    const tgtUuid = uuidFromDistinctId(team.id, targetDistinct)

                    // Arrange: create persons on both DBs
                    const src = await repository.createPerson(timestamp, {}, {}, {}, team.id, null, false, srcUuid, [
                        { distinctId: sourceDistinct },
                    ])
                    const tgt = await repository.createPerson(timestamp, {}, {}, {}, team.id, null, false, tgtUuid, [
                        { distinctId: targetDistinct },
                    ])
                    expect(src.success && tgt.success).toBe(true)
                    if (!src.success || !tgt.success) {
                        throw new Error('Failed to create test persons')
                    }

                    // Force secondary failure during merge
                    const originalQuery = migrationPostgres.query.bind(migrationPostgres)
                    const spy = jest
                        .spyOn(migrationPostgres, 'query')
                        .mockImplementation(async (use, query, params, tag) => {
                            const queryString = typeof query === 'string' ? query : query.text
                            const queryTag = typeof tag === 'string' ? tag : ''
                            if (
                                (queryString.includes('UPDATE posthog_person') && queryTag.includes('updatePerson')) ||
                                (queryString.includes('UPDATE posthog_persondistinctid') &&
                                    queryTag.includes('updateDistinctIdPerson'))
                            ) {
                                throw new Error('Simulated secondary failure in BothExist merge')
                            }
                            return originalQuery(use, query, params, tag)
                        })

                    const svc = personMergeServiceDual({
                        team,
                        distinctId: targetDistinct,
                        event: '$identify',
                        timestamp,
                        properties: { $anon_distinct_id: sourceDistinct },
                    })

                    const [maybePerson, acks] = await svc.handleIdentifyOrAlias()
                    // Service swallows the error and returns undefined
                    expect(maybePerson).toBeUndefined()
                    await expect(acks).resolves.toBeUndefined()

                    spy.mockRestore()

                    // Assert: no changes on primary
                    const primaryPersons = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT id, uuid, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-primary-rollback-bothexist'
                    )
                    expect(primaryPersons.rows.length).toBe(2)
                    expect(primaryPersons.rows.map((r: any) => r.uuid).sort()).toEqual([srcUuid, tgtUuid].sort())
                    primaryPersons.rows.forEach((r: any) => {
                        expect(r.is_identified).toBe(false)
                        expect(Number(r.version || 0)).toBe(0)
                    })

                    const primaryPdi = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT p.uuid, pd.distinct_id FROM posthog_persondistinctid pd JOIN posthog_person p ON p.id = pd.person_id WHERE p.team_id = $1 ORDER BY distinct_id',
                        [team.id],
                        'verify-primary-rollback-bothexist-pdi'
                    )
                    expect(primaryPdi.rows).toEqual([
                        { uuid: srcUuid, distinct_id: sourceDistinct },
                        { uuid: tgtUuid, distinct_id: targetDistinct },
                    ])

                    // Assert: no changes on secondary
                    const secondaryPersons = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT id, uuid, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-secondary-rollback-bothexist'
                    )
                    expect(secondaryPersons.rows.length).toBe(2)
                    expect(secondaryPersons.rows.map((r: any) => r.uuid).sort()).toEqual([srcUuid, tgtUuid].sort())
                    secondaryPersons.rows.forEach((r: any) => {
                        expect(r.is_identified).toBe(false)
                        expect(Number(r.version || 0)).toBe(0)
                    })

                    const secondaryPdi = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT p.uuid, pd.distinct_id FROM posthog_persondistinctid pd JOIN posthog_person p ON p.id = pd.person_id WHERE p.team_id = $1 ORDER BY distinct_id',
                        [team.id],
                        'verify-secondary-rollback-bothexist-pdi'
                    )
                    expect(secondaryPdi.rows).toEqual([
                        { uuid: srcUuid, distinct_id: sourceDistinct },
                        { uuid: tgtUuid, distinct_id: targetDistinct },
                    ])
                })

                it('rolls back on cohorts/flags update failure', async () => {
                    const team = await getFirstTeam(hub)
                    const timestamp = DateTime.fromISO('2024-02-03T12:00:00.000Z').toUTC()

                    const sourceDistinct = 'rb-cf-src'
                    const targetDistinct = 'rb-cf-tgt'
                    const srcUuid = uuidFromDistinctId(team.id, sourceDistinct)
                    const tgtUuid = uuidFromDistinctId(team.id, targetDistinct)

                    // Arrange: create persons on both DBs
                    const src = await repository.createPerson(timestamp, {}, {}, {}, team.id, null, false, srcUuid, [
                        { distinctId: sourceDistinct },
                    ])
                    const tgt = await repository.createPerson(timestamp, {}, {}, {}, team.id, null, false, tgtUuid, [
                        { distinctId: targetDistinct },
                    ])
                    expect(src.success && tgt.success).toBe(true)
                    if (!src.success || !tgt.success) {
                        throw new Error('Failed to create test persons')
                    }
                    const srcPerson = src.person
                    const _tgtPerson = tgt.person

                    // Seed cohort + feature flag overrides for source on both DBs
                    const seedCohortAndFlags = async (router: PostgresRouter) => {
                        await router.query(
                            PostgresUse.PERSONS_WRITE,
                            'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                            [42, srcPerson.id, team.id],
                            'seed-cohortpeople-rollback'
                        )
                        await router.query(
                            PostgresUse.PERSONS_WRITE,
                            'INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) VALUES ($1, $2, $3, $4)',
                            [team.id, srcPerson.id, 'flag-x', 'hash-x-src'],
                            'seed-ff-x-rollback'
                        )
                    }
                    await seedCohortAndFlags(postgres)
                    await seedCohortAndFlags(migrationPostgres)

                    // Force failure specifically on cohorts/flags update (secondary side)
                    const spy = jest
                        .spyOn((repository as any).secondaryRepo, 'updateCohortsAndFeatureFlagsForMerge')
                        .mockRejectedValue(new Error('Simulated cohorts/flags update failure'))

                    const svc = personMergeServiceDual({
                        team,
                        distinctId: targetDistinct,
                        event: '$identify',
                        timestamp,
                        properties: { $anon_distinct_id: sourceDistinct },
                    })

                    const [maybePerson, acks] = await svc.handleIdentifyOrAlias()
                    expect(maybePerson).toBeUndefined()
                    await expect(acks).resolves.toBeUndefined()

                    spy.mockRestore()

                    // Assert: primary remains unchanged
                    const pPersons = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT id, uuid, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-primary-rollback-cf-persons'
                    )
                    expect(pPersons.rows.length).toBe(2)
                    expect(pPersons.rows.map((r: any) => r.uuid).sort()).toEqual([srcUuid, tgtUuid].sort())
                    pPersons.rows.forEach((r: any) => {
                        expect(r.is_identified).toBe(false)
                        expect(Number(r.version || 0)).toBe(0)
                    })

                    const pPdi = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT p.uuid, pd.distinct_id FROM posthog_persondistinctid pd JOIN posthog_person p ON p.id = pd.person_id WHERE p.team_id = $1 ORDER BY distinct_id',
                        [team.id],
                        'verify-primary-rollback-cf-pdi'
                    )
                    expect(pPdi.rows).toEqual([
                        { uuid: srcUuid, distinct_id: sourceDistinct },
                        { uuid: tgtUuid, distinct_id: targetDistinct },
                    ])

                    const pCohort = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-primary-rollback-cf-cohort'
                    )
                    expect(pCohort.rows).toEqual([{ cohort_id: 42, person_id: srcPerson.id }])

                    const pOverrides = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-primary-rollback-cf-ff'
                    )
                    expect(pOverrides.rows).toEqual([
                        { feature_flag_key: 'flag-x', hash_key: 'hash-x-src', person_id: srcPerson.id },
                    ])

                    // Assert: secondary remains unchanged
                    const sPersons = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT id, uuid, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-secondary-rollback-cf-persons'
                    )
                    expect(sPersons.rows.length).toBe(2)
                    expect(sPersons.rows.map((r: any) => r.uuid).sort()).toEqual([srcUuid, tgtUuid].sort())
                    sPersons.rows.forEach((r: any) => {
                        expect(r.is_identified).toBe(false)
                        expect(Number(r.version || 0)).toBe(0)
                    })

                    const sPdi = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT p.uuid, pd.distinct_id FROM posthog_persondistinctid pd JOIN posthog_person p ON p.id = pd.person_id WHERE p.team_id = $1 ORDER BY distinct_id',
                        [team.id],
                        'verify-secondary-rollback-cf-pdi'
                    )
                    expect(sPdi.rows).toEqual([
                        { uuid: srcUuid, distinct_id: sourceDistinct },
                        { uuid: tgtUuid, distinct_id: targetDistinct },
                    ])

                    const sCohort = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-secondary-rollback-cf-cohort'
                    )
                    expect(sCohort.rows).toEqual([{ cohort_id: 42, person_id: srcPerson.id }])

                    const sOverrides = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 ORDER BY id',
                        [team.id],
                        'verify-secondary-rollback-cf-ff'
                    )
                    expect(sOverrides.rows).toEqual([
                        { feature_flag_key: 'flag-x', hash_key: 'hash-x-src', person_id: srcPerson.id },
                    ])
                })
            })
        })

        describe('$create_alias events', () => {
            it('performs alias merge across both DBs', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-05T10:00:00.000Z').toUTC()
                const existingDistinctId = 'existing-alias-1'
                const aliasDistinctId = 'alias-1'

                // Create existing person with is_identified=true
                const existingResult = await repository.createPerson(
                    timestamp,
                    { name: 'Existing User' },
                    {},
                    {},
                    team.id,
                    null,
                    true, // is_identified = true
                    uuidFromDistinctId(team.id, existingDistinctId),
                    [{ distinctId: existingDistinctId, version: 0 }]
                )
                expect(existingResult.success).toBe(true)

                // Perform $create_alias: aliasDistinctId creates alias to existingDistinctId
                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: aliasDistinctId,
                    event: '$create_alias',
                    timestamp,
                    properties: { alias: existingDistinctId },
                })

                const [person, acks] = await mergeService.handleIdentifyOrAlias()
                expect(person).toBeDefined()
                await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                // Verify both distinct IDs point to same person in both DBs
                const primaryDistincts = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                    [person!.id],
                    'verify-primary-alias-distincts'
                )
                const secondaryDistincts = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                    [team.id, person!.uuid],
                    'verify-secondary-alias-distincts'
                )

                const primaryIds = primaryDistincts.rows.map((r) => r.distinct_id).sort()
                const secondaryIds = secondaryDistincts.rows.map((r) => r.distinct_id).sort()

                expect(primaryIds).toEqual([aliasDistinctId, existingDistinctId])
                expect(secondaryIds).toEqual([aliasDistinctId, existingDistinctId])
                expect(person!.is_identified).toBe(true)
            })

            it('respects is_identified restrictions', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-05T11:00:00.000Z').toUTC()
                const unidentifiedDistinctId = 'unidentified-alias-1'
                const identifiedDistinctId = 'identified-alias-1'

                // Create an unidentified person (is_identified=false)
                const unidentifiedResult = await repository.createPerson(
                    timestamp,
                    { name: 'Unidentified User' },
                    {},
                    {},
                    team.id,
                    null,
                    false, // is_identified = false
                    uuidFromDistinctId(team.id, unidentifiedDistinctId),
                    [{ distinctId: unidentifiedDistinctId, version: 0 }]
                )
                expect(unidentifiedResult.success).toBe(true)

                // Create an identified person (is_identified=true)
                const identifiedResult = await repository.createPerson(
                    timestamp,
                    { name: 'Identified User' },
                    {},
                    {},
                    team.id,
                    null,
                    true, // is_identified = true
                    uuidFromDistinctId(team.id, identifiedDistinctId),
                    [{ distinctId: identifiedDistinctId, version: 0 }]
                )
                expect(identifiedResult.success).toBe(true)

                // Try $create_alias from identified to unidentified - should merge since both exist
                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: identifiedDistinctId,
                    event: '$create_alias',
                    timestamp,
                    properties: { alias: unidentifiedDistinctId },
                })

                const [_person, acks] = await mergeService.handleIdentifyOrAlias()
                await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                // Should merge since both persons exist - only one person should remain
                const primaryPersons = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-primary-alias-merged'
                )
                const secondaryPersons = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-alias-merged'
                )

                expect(Number(primaryPersons.rows[0].count)).toBe(1)
                expect(Number(secondaryPersons.rows[0].count)).toBe(1)
            })

            it('rolls back on failure', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-05T12:00:00.000Z').toUTC()
                const existingDistinctId = 'existing-alias-rollback'
                const aliasDistinctId = 'alias-rollback'

                // Create existing person
                const existingResult = await repository.createPerson(
                    timestamp,
                    { name: 'Existing User' },
                    {},
                    {},
                    team.id,
                    null,
                    true,
                    uuidFromDistinctId(team.id, existingDistinctId),
                    [{ distinctId: existingDistinctId, version: 0 }]
                )
                expect(existingResult.success).toBe(true)

                // Force secondary failure during alias merge
                const spy = jest
                    .spyOn((repository as any).secondaryRepo, 'addDistinctId')
                    .mockRejectedValue(new Error('simulated secondary alias failure'))

                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: aliasDistinctId,
                    event: '$create_alias',
                    timestamp,
                    properties: { alias: existingDistinctId },
                })

                const [maybePerson, acks] = await mergeService.handleIdentifyOrAlias()
                expect(maybePerson).toBeUndefined()
                await expect(acks).resolves.toBeUndefined()

                spy.mockRestore()

                // Verify rollback - only original person and distinct ID should exist
                const primaryDistincts = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 ORDER BY distinct_id',
                    [team.id],
                    'verify-primary-alias-rollback'
                )
                const secondaryDistincts = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 ORDER BY distinct_id',
                    [team.id],
                    'verify-secondary-alias-rollback'
                )

                expect(primaryDistincts.rows.map((r) => r.distinct_id)).toEqual([existingDistinctId])
                expect(secondaryDistincts.rows.map((r) => r.distinct_id)).toEqual([existingDistinctId])
            })
        })

        describe('$merge_dangerously events', () => {
            it('merges regardless of is_identified status', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-06T10:00:00.000Z').toUTC()
                const identifiedDistinctId = 'identified-merge-dangerous'
                const unidentifiedDistinctId = 'unidentified-merge-dangerous'

                // Create identified person
                const identifiedResult = await repository.createPerson(
                    timestamp,
                    { name: 'Identified User', prop1: 'value1' },
                    {},
                    {},
                    team.id,
                    null,
                    true, // is_identified = true
                    uuidFromDistinctId(team.id, identifiedDistinctId),
                    [{ distinctId: identifiedDistinctId, version: 0 }]
                )
                expect(identifiedResult.success).toBe(true)

                // Create unidentified person
                const unidentifiedResult = await repository.createPerson(
                    timestamp,
                    { name: 'Unidentified User', prop2: 'value2' },
                    {},
                    {},
                    team.id,
                    null,
                    false, // is_identified = false
                    uuidFromDistinctId(team.id, unidentifiedDistinctId),
                    [{ distinctId: unidentifiedDistinctId, version: 0 }]
                )
                expect(unidentifiedResult.success).toBe(true)

                // Perform $merge_dangerously - should merge despite is_identified restrictions
                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: identifiedDistinctId,
                    event: '$merge_dangerously',
                    timestamp,
                    properties: {
                        alias: unidentifiedDistinctId,
                        $set: { merged_prop: 'dangerous_merge' },
                    },
                })

                const [person, acks] = await mergeService.handleIdentifyOrAlias()
                expect(person).toBeDefined()
                await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                // Verify merge happened - only one person should remain with both distinct IDs
                const primaryPersons = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT id, uuid, properties, is_identified FROM posthog_person WHERE team_id = $1 ORDER BY id',
                    [team.id],
                    'verify-primary-dangerous-merge'
                )
                expect(primaryPersons.rows.length).toBe(1)
                expect(primaryPersons.rows[0].properties).toMatchObject({
                    prop1: 'value1',
                    prop2: 'value2',
                    merged_prop: 'dangerous_merge',
                })
                expect(primaryPersons.rows[0].is_identified).toBe(true)

                const secondaryPersons = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT id, uuid, properties, is_identified FROM posthog_person WHERE team_id = $1 ORDER BY id',
                    [team.id],
                    'verify-secondary-dangerous-merge'
                )
                expect(secondaryPersons.rows.length).toBe(1)
                expect(secondaryPersons.rows[0].properties).toMatchObject({
                    prop1: 'value1',
                    prop2: 'value2',
                    merged_prop: 'dangerous_merge',
                })

                // Verify both distinct IDs exist
                const primaryDistincts = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                    [primaryPersons.rows[0].id],
                    'verify-primary-dangerous-distincts'
                )
                const secondaryDistincts = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                    [team.id, secondaryPersons.rows[0].uuid],
                    'verify-secondary-dangerous-distincts'
                )

                const primaryIds = primaryDistincts.rows.map((r) => r.distinct_id).sort()
                const secondaryIds = secondaryDistincts.rows.map((r) => r.distinct_id).sort()

                expect(primaryIds).toEqual([identifiedDistinctId, unidentifiedDistinctId])
                expect(secondaryIds).toEqual([identifiedDistinctId, unidentifiedDistinctId])
            })

            it('rolls back on failure', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-06T11:00:00.000Z').toUTC()
                const person1DistinctId = 'dangerous-rollback-1'
                const person2DistinctId = 'dangerous-rollback-2'

                // Create two persons
                const person1Result = await repository.createPerson(
                    timestamp,
                    { name: 'Person 1' },
                    {},
                    {},
                    team.id,
                    null,
                    true,
                    uuidFromDistinctId(team.id, person1DistinctId),
                    [{ distinctId: person1DistinctId, version: 0 }]
                )
                const person2Result = await repository.createPerson(
                    timestamp,
                    { name: 'Person 2' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, person2DistinctId),
                    [{ distinctId: person2DistinctId, version: 0 }]
                )
                expect(person1Result.success && person2Result.success).toBe(true)

                // Force secondary failure during dangerous merge by mocking moveDistinctIds
                const spy = jest
                    .spyOn((repository as any).secondaryRepo, 'moveDistinctIds')
                    .mockRejectedValue(new Error('simulated secondary dangerous merge failure'))

                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: person1DistinctId,
                    event: '$merge_dangerously',
                    timestamp,
                    properties: { alias: person2DistinctId },
                })

                const [maybePerson, acks] = await mergeService.handleIdentifyOrAlias()
                // Service should handle the error and return undefined
                expect(maybePerson).toBeUndefined()
                await acks // Wait for acks to complete

                spy.mockRestore()

                // Verify rollback - both persons should still exist separately
                const primaryPersons = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-primary-dangerous-rollback'
                )
                const secondaryPersons = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-dangerous-rollback'
                )

                expect(Number(primaryPersons.rows[0].count)).toBe(2)
                expect(Number(secondaryPersons.rows[0].count)).toBe(2)

                // Verify distinct IDs remain separate
                const primaryDistincts = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 ORDER BY distinct_id',
                    [team.id],
                    'verify-primary-dangerous-rollback-distincts'
                )
                const secondaryDistincts = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 ORDER BY distinct_id',
                    [team.id],
                    'verify-secondary-dangerous-rollback-distincts'
                )

                expect(primaryDistincts.rows.map((r) => r.distinct_id).sort()).toEqual([
                    person1DistinctId,
                    person2DistinctId,
                ])
                expect(secondaryDistincts.rows.map((r) => r.distinct_id).sort()).toEqual([
                    person1DistinctId,
                    person2DistinctId,
                ])
            })
        })
    })
    // Note: Property updates are tested at the PersonPropertyService level, not the repository level
    // The repository updatePerson method expects Partial<InternalPerson>, not $set/$set_once operations

    describe('Personless Distinct ID Handling', () => {
        describe('Version selection logic', () => {
            it('uses version 0 when distinct ID is new', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-08T10:00:00.000Z').toUTC()
                const newDistinctId = 'brand-new-distinct-id'

                // Create person with new distinct ID
                const createResult = await repository.createPerson(
                    timestamp,
                    { name: 'New User' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, newDistinctId),
                    [{ distinctId: newDistinctId, version: 0 }]
                )
                expect(createResult.success).toBe(true)

                // Verify version 0 in both DBs
                const primaryVersion = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT version FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [newDistinctId, team.id],
                    'verify-primary-new-version'
                )
                const secondaryVersion = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT version FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [newDistinctId, team.id],
                    'verify-secondary-new-version'
                )

                expect(Number(primaryVersion.rows[0].version)).toBe(0)
                expect(Number(secondaryVersion.rows[0].version)).toBe(0)
            })

            it('uses version 1 when distinct ID was used in personless mode', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-08T11:00:00.000Z').toUTC()
                const personlessDistinctId = 'personless-distinct-id'

                // Add distinct ID to personless table first
                await repository.addPersonlessDistinctId(team.id, personlessDistinctId)

                // Verify personless distinct ID exists in both DBs
                const primaryPersonless = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-primary-personless-before'
                )
                const secondaryPersonless = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-secondary-personless-before'
                )

                expect(primaryPersonless.rows.length).toBe(1)
                expect(secondaryPersonless.rows.length).toBe(1)

                // Create person with previously personless distinct ID - explicitly set version 1
                const createResult = await repository.createPerson(
                    timestamp,
                    { name: 'Previously Personless User' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, personlessDistinctId),
                    [{ distinctId: personlessDistinctId, version: 1 }] // Explicitly set version 1 for personless
                )
                expect(createResult.success).toBe(true)

                // Verify version 1 in both DBs
                const primaryVersion = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT version FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-primary-personless-version'
                )
                const secondaryVersion = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT version FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-secondary-personless-version'
                )

                expect(Number(primaryVersion.rows[0].version)).toBe(1)
                expect(Number(secondaryVersion.rows[0].version)).toBe(1)

                // Verify personless distinct ID still exists (cleanup happens at higher levels)
                const primaryPersonlessAfter = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-primary-personless-after'
                )
                const secondaryPersonlessAfter = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-secondary-personless-after'
                )

                expect(primaryPersonlessAfter.rows.length).toBe(1)
                expect(secondaryPersonlessAfter.rows.length).toBe(1)
            })

            it('handles mixed scenarios correctly', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-08T12:00:00.000Z').toUTC()
                const existingDistinctId = 'existing-mixed'
                const personlessDistinctId = 'personless-mixed'

                // Create existing person
                const existingResult = await repository.createPerson(
                    timestamp,
                    { name: 'Existing User' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, existingDistinctId),
                    [{ distinctId: existingDistinctId, version: 0 }]
                )
                expect(existingResult.success).toBe(true)

                // Add personless distinct ID
                await repository.addPersonlessDistinctId(team.id, personlessDistinctId)

                // Perform identify to merge them
                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: personlessDistinctId,
                    event: '$identify',
                    timestamp,
                    properties: { $anon_distinct_id: existingDistinctId },
                })

                const [person, acks] = await mergeService.handleIdentifyOrAlias()
                expect(person).toBeDefined()
                await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                // Verify versions: existing should stay 0, personless should become 1
                const primaryVersions = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id, version FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                    [person!.id],
                    'verify-primary-mixed-versions'
                )
                const secondaryVersions = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id, version FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                    [team.id, person!.uuid],
                    'verify-secondary-mixed-versions'
                )

                const primaryVersionMap = primaryVersions.rows.reduce((acc: any, row: any) => {
                    acc[row.distinct_id] = Number(row.version)
                    return acc
                }, {})
                const secondaryVersionMap = secondaryVersions.rows.reduce((acc: any, row: any) => {
                    acc[row.distinct_id] = Number(row.version)
                    return acc
                }, {})

                expect(primaryVersionMap[existingDistinctId]).toBe(0)
                expect(primaryVersionMap[personlessDistinctId]).toBe(1)
                expect(secondaryVersionMap).toEqual(primaryVersionMap)
            })
        })

        describe('Rollback scenarios', () => {
            it('rolls back personless updates on merge failure', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-08T13:00:00.000Z').toUTC()
                const existingDistinctId = 'existing-rollback-personless'
                const personlessDistinctId = 'personless-rollback'

                // Create existing person
                const existingResult = await repository.createPerson(
                    timestamp,
                    { name: 'Existing User' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, existingDistinctId),
                    [{ distinctId: existingDistinctId, version: 0 }]
                )
                expect(existingResult.success).toBe(true)

                // Add personless distinct ID
                await repository.addPersonlessDistinctId(team.id, personlessDistinctId)

                // Verify personless ID exists before merge attempt
                const primaryPersonlessBefore = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-primary-personless-before-rollback'
                )
                const secondaryPersonlessBefore = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-secondary-personless-before-rollback'
                )

                expect(primaryPersonlessBefore.rows.length).toBe(1)
                expect(secondaryPersonlessBefore.rows.length).toBe(1)

                // Force secondary failure during merge
                const spy = jest
                    .spyOn((repository as any).secondaryRepo, 'addDistinctId')
                    .mockRejectedValue(new Error('simulated secondary personless merge failure'))

                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: personlessDistinctId,
                    event: '$identify',
                    timestamp,
                    properties: { $anon_distinct_id: existingDistinctId },
                })

                const [maybePerson, acks] = await mergeService.handleIdentifyOrAlias()
                expect(maybePerson).toBeUndefined()
                await expect(acks).resolves.toBeUndefined()

                spy.mockRestore()

                // Verify rollback - personless distinct ID should still exist
                const primaryPersonlessAfter = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-primary-personless-after-rollback'
                )
                const secondaryPersonlessAfter = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_personlessdistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-secondary-personless-after-rollback'
                )

                expect(primaryPersonlessAfter.rows.length).toBe(1)
                expect(secondaryPersonlessAfter.rows.length).toBe(1)

                // Verify no new person distinct ID was created
                const primaryPersonDistinct = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-primary-person-distinct-rollback'
                )
                const secondaryPersonDistinct = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE distinct_id = $1 AND team_id = $2',
                    [personlessDistinctId, team.id],
                    'verify-secondary-person-distinct-rollback'
                )

                expect(primaryPersonDistinct.rows.length).toBe(0)
                expect(secondaryPersonDistinct.rows.length).toBe(0)

                // Verify original person remains unchanged
                const primaryPerson = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_persondistinctid WHERE person_id = $1',
                    [existingResult.person.id],
                    'verify-primary-original-person-rollback'
                )
                expect(Number(primaryPerson.rows[0].count)).toBe(1) // Only original distinct ID
            })
        })
    })

    describe('Cohorts and Feature Flags', () => {
        it('updates cohorts during merge', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-09T10:00:00.000Z').toUTC()
            const sourceDistinctId = 'cohort-source'
            const targetDistinctId = 'cohort-target'

            // Create two persons
            const sourceResult = await repository.createPerson(
                timestamp,
                { name: 'Source User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, sourceDistinctId),
                [{ distinctId: sourceDistinctId, version: 0 }]
            )
            const targetResult = await repository.createPerson(
                timestamp,
                { name: 'Target User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, targetDistinctId),
                [{ distinctId: targetDistinctId, version: 0 }]
            )
            expect(sourceResult.success && targetResult.success).toBe(true)

            // Add cohort membership for source person in both DBs
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                [99, sourceResult.person.id, team.id],
                'add-primary-cohort'
            )
            await migrationPostgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                [99, sourceResult.person.id, team.id],
                'add-secondary-cohort'
            )

            // Perform merge
            const mergeService = personMergeServiceDual({
                team,
                distinctId: targetDistinctId,
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: sourceDistinctId },
            })

            const [person, acks] = await mergeService.handleIdentifyOrAlias()
            expect(person).toBeDefined()
            await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

            // Verify cohort moved to target person in both DBs
            const primaryCohort = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE team_id = $1',
                [team.id],
                'verify-primary-cohort-moved'
            )
            const secondaryCohort = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE team_id = $1',
                [team.id],
                'verify-secondary-cohort-moved'
            )

            expect(primaryCohort.rows.length).toBe(1)
            expect(primaryCohort.rows[0].cohort_id).toBe(99)
            expect(primaryCohort.rows[0].person_id).toBe(targetResult.person.id)
            expect(secondaryCohort.rows).toEqual(primaryCohort.rows)
        })

        it('updates feature flag overrides during merge', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-09T11:00:00.000Z').toUTC()
            const sourceDistinctId = 'ff-source'
            const targetDistinctId = 'ff-target'

            // Create two persons
            const sourceResult = await repository.createPerson(
                timestamp,
                { name: 'Source User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, sourceDistinctId),
                [{ distinctId: sourceDistinctId, version: 0 }]
            )
            const targetResult = await repository.createPerson(
                timestamp,
                { name: 'Target User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, targetDistinctId),
                [{ distinctId: targetDistinctId, version: 0 }]
            )
            expect(sourceResult.success && targetResult.success).toBe(true)

            // Add feature flag overrides for source person in both DBs
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) VALUES ($1, $2, $3, $4)',
                [team.id, sourceResult.person.id, 'test-flag', 'test-hash'],
                'add-primary-ff'
            )
            await migrationPostgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) VALUES ($1, $2, $3, $4)',
                [team.id, sourceResult.person.id, 'test-flag', 'test-hash'],
                'add-secondary-ff'
            )

            // Perform merge
            const mergeService = personMergeServiceDual({
                team,
                distinctId: targetDistinctId,
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: sourceDistinctId },
            })

            const [person, acks] = await mergeService.handleIdentifyOrAlias()
            expect(person).toBeDefined()
            await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

            // Verify feature flag override moved to target person in both DBs
            const primaryFF = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride WHERE team_id = $1',
                [team.id],
                'verify-primary-ff-moved'
            )
            const secondaryFF = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride WHERE team_id = $1',
                [team.id],
                'verify-secondary-ff-moved'
            )

            expect(primaryFF.rows.length).toBe(1)
            expect(primaryFF.rows[0].feature_flag_key).toBe('test-flag')
            expect(primaryFF.rows[0].hash_key).toBe('test-hash')
            expect(primaryFF.rows[0].person_id).toBe(targetResult.person.id)
            expect(secondaryFF.rows).toEqual(primaryFF.rows)
        })

        it('rolls back cohort updates on failure', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-09T12:00:00.000Z').toUTC()
            const sourceDistinctId = 'cohort-rollback-source'
            const targetDistinctId = 'cohort-rollback-target'

            // Create two persons
            const sourceResult = await repository.createPerson(
                timestamp,
                { name: 'Source User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, sourceDistinctId),
                [{ distinctId: sourceDistinctId, version: 0 }]
            )
            const targetResult = await repository.createPerson(
                timestamp,
                { name: 'Target User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, targetDistinctId),
                [{ distinctId: targetDistinctId, version: 0 }]
            )
            expect(sourceResult.success && targetResult.success).toBe(true)

            // Add cohort membership for source in both DBs
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                [100, sourceResult.person.id, team.id],
                'add-primary-cohort-rollback'
            )
            await migrationPostgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                [100, sourceResult.person.id, team.id],
                'add-secondary-cohort-rollback'
            )

            // Force failure during cohort update
            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'updateCohortsAndFeatureFlagsForMerge')
                .mockRejectedValue(new Error('simulated cohort update failure'))

            const mergeService = personMergeServiceDual({
                team,
                distinctId: targetDistinctId,
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: sourceDistinctId },
            })

            const [maybePerson, acks] = await mergeService.handleIdentifyOrAlias()
            expect(maybePerson).toBeUndefined()
            await expect(acks).resolves.toBeUndefined()

            spy.mockRestore()

            // Verify rollback - cohort should remain with source person
            const primaryCohort = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE team_id = $1',
                [team.id],
                'verify-primary-cohort-rollback'
            )
            const secondaryCohort = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT cohort_id, person_id FROM posthog_cohortpeople WHERE team_id = $1',
                [team.id],
                'verify-secondary-cohort-rollback'
            )

            expect(primaryCohort.rows.length).toBe(1)
            expect(primaryCohort.rows[0].person_id).toBe(sourceResult.person.id)
            expect(secondaryCohort.rows).toEqual(primaryCohort.rows)

            // Verify persons remain separate
            const primaryPersons = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                [team.id],
                'verify-primary-persons-rollback'
            )
            expect(Number(primaryPersons.rows[0].count)).toBe(2)
        })

        it('rolls back feature flag updates on failure', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-09T13:00:00.000Z').toUTC()
            const sourceDistinctId = 'ff-rollback-source'
            const targetDistinctId = 'ff-rollback-target'

            // Create two persons
            const sourceResult = await repository.createPerson(
                timestamp,
                { name: 'Source User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, sourceDistinctId),
                [{ distinctId: sourceDistinctId, version: 0 }]
            )
            const targetResult = await repository.createPerson(
                timestamp,
                { name: 'Target User' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, targetDistinctId),
                [{ distinctId: targetDistinctId, version: 0 }]
            )
            expect(sourceResult.success && targetResult.success).toBe(true)

            // Add feature flag override for source in both DBs
            await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) VALUES ($1, $2, $3, $4)',
                [team.id, sourceResult.person.id, 'rollback-flag', 'rollback-hash'],
                'add-primary-ff-rollback'
            )
            await migrationPostgres.query(
                PostgresUse.PERSONS_WRITE,
                'INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key) VALUES ($1, $2, $3, $4)',
                [team.id, sourceResult.person.id, 'rollback-flag', 'rollback-hash'],
                'add-secondary-ff-rollback'
            )

            // Force failure during feature flag update on secondary by mocking the method
            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'moveDistinctIds')
                .mockRejectedValue(new Error('Simulated feature flag update failure'))

            const mergeService = personMergeServiceDual({
                team,
                distinctId: targetDistinctId,
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: sourceDistinctId },
            })

            const [maybePerson, acks] = await mergeService.handleIdentifyOrAlias()
            expect(maybePerson).toBeUndefined()
            await expect(acks).resolves.toBeUndefined()

            spy.mockRestore()

            // Verify rollback - feature flag should remain with source person
            const primaryFF = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride WHERE team_id = $1',
                [team.id],
                'verify-primary-ff-rollback'
            )
            const secondaryFF = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride WHERE team_id = $1',
                [team.id],
                'verify-secondary-ff-rollback'
            )

            expect(primaryFF.rows.length).toBe(1)
            expect(primaryFF.rows[0].person_id).toBe(sourceResult.person.id)
            expect(secondaryFF.rows).toEqual(primaryFF.rows)

            // Verify persons remain separate
            const primaryPersons = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                [team.id],
                'verify-primary-persons-ff-rollback'
            )
            expect(Number(primaryPersons.rows[0].count)).toBe(2)
        })
    })

    describe('Batch Processing', () => {
        describe('Store-level operations', () => {
            it('flushes dual writes correctly', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-10T10:00:00.000Z').toUTC()
                const personsStore = new BatchWritingPersonsStoreForBatch(repository, hub.db.kafkaProducer)

                // Create multiple persons through the store
                const distinctIds = ['batch-1', 'batch-2', 'batch-3']
                const persons = []

                for (const distinctId of distinctIds) {
                    const createResult = await repository.createPerson(
                        timestamp,
                        { name: `Batch User ${distinctId}` },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuidFromDistinctId(team.id, distinctId),
                        [{ distinctId, version: 0 }]
                    )
                    expect(createResult.success).toBe(true)
                    persons.push(createResult.person)
                }

                // Flush the store
                const kafkaMessages = await personsStore.flush()
                await hub.db.kafkaProducer.queueMessages(kafkaMessages.map((message) => message.topicMessage))
                await hub.db.kafkaProducer.flush()

                // Verify all persons exist in both DBs
                const primaryCount = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-primary-batch-count'
                )
                const secondaryCount = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-batch-count'
                )

                expect(Number(primaryCount.rows[0].count)).toBe(distinctIds.length)
                expect(Number(secondaryCount.rows[0].count)).toBe(distinctIds.length)

                // Verify all distinct IDs exist
                const primaryDistincts = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                    [team.id],
                    'verify-primary-batch-distincts'
                )
                const secondaryDistincts = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-batch-distincts'
                )

                expect(Number(primaryDistincts.rows[0].count)).toBe(distinctIds.length)
                expect(Number(secondaryDistincts.rows[0].count)).toBe(distinctIds.length)
            })

            it('handles batch failures with partial rollback', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-10T11:00:00.000Z').toUTC()

                // Create first person successfully
                const firstResult = await repository.createPerson(
                    timestamp,
                    { name: 'First Batch User' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, 'batch-success'),
                    [{ distinctId: 'batch-success', version: 0 }]
                )
                expect(firstResult.success).toBe(true)

                // Force failure on second create
                const spy = jest
                    .spyOn((repository as any).secondaryRepo, 'createPerson')
                    .mockRejectedValue(new Error('simulated batch failure'))

                // Try to create second person - should fail due to mocked error
                await expect(
                    repository.createPerson(
                        timestamp,
                        { name: 'Second Batch User' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuidFromDistinctId(team.id, 'batch-failure'),
                        [{ distinctId: 'batch-failure', version: 0 }]
                    )
                ).rejects.toThrow('simulated batch failure')

                spy.mockRestore()

                // Verify only first person exists in both DBs
                const primaryPersons = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-primary-batch-partial'
                )
                const secondaryPersons = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-batch-partial'
                )

                expect(primaryPersons.rows.length).toBe(1)
                expect(primaryPersons.rows[0].uuid).toBe(firstResult.person.uuid)
                expect(secondaryPersons.rows.length).toBe(1)
                expect(secondaryPersons.rows[0].uuid).toBe(firstResult.person.uuid)

                // Verify failed person doesn't exist anywhere
                const primaryFailed = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuidFromDistinctId(team.id, 'batch-failure')],
                    'verify-primary-batch-failed'
                )
                const secondaryFailed = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuidFromDistinctId(team.id, 'batch-failure')],
                    'verify-secondary-batch-failed'
                )

                expect(primaryFailed.rows.length).toBe(0)
                expect(secondaryFailed.rows.length).toBe(0)
            })
        })

        describe('Transaction boundaries', () => {
            it('maintains 2PC across complex batch operations', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-10T12:00:00.000Z').toUTC()

                // Test complex operation: create person, then merge with another
                const person1Result = await repository.createPerson(
                    timestamp,
                    { name: 'Complex User 1', prop1: 'value1' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, 'complex-1'),
                    [{ distinctId: 'complex-1', version: 0 }]
                )
                expect(person1Result.success).toBe(true)

                const person2Result = await repository.createPerson(
                    timestamp,
                    { name: 'Complex User 2', prop2: 'value2' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, 'complex-2'),
                    [{ distinctId: 'complex-2', version: 0 }]
                )
                expect(person2Result.success).toBe(true)

                // Perform complex merge with property updates
                const mergeService = personMergeServiceDual({
                    team,
                    distinctId: 'complex-2',
                    event: '$identify',
                    timestamp,
                    properties: {
                        $anon_distinct_id: 'complex-1',
                        $set: { merged: true, complexProp: 'complex value' },
                    },
                })

                const [mergedPerson, acks] = await mergeService.handleIdentifyOrAlias()
                expect(mergedPerson).toBeDefined()
                await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

                // Verify complex operation completed atomically across both DBs
                const primaryPerson = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid, properties FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-primary-complex-merge'
                )
                const secondaryPerson = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid, properties FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-complex-merge'
                )

                expect(primaryPerson.rows.length).toBe(1)
                expect(primaryPerson.rows[0].properties).toMatchObject({
                    prop1: 'value1',
                    prop2: 'value2',
                    merged: true,
                    complexProp: 'complex value',
                })
                expect(secondaryPerson.rows).toEqual(primaryPerson.rows)

                // Verify both distinct IDs point to merged person
                const primaryDistincts = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                    [team.id],
                    'verify-primary-complex-distincts'
                )
                const secondaryDistincts = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-complex-distincts'
                )

                expect(Number(primaryDistincts.rows[0].count)).toBe(2)
                expect(Number(secondaryDistincts.rows[0].count)).toBe(2)
            })

            it('handles nested transaction scenarios', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-10T13:00:00.000Z').toUTC()

                // Simulate nested transaction scenario by creating person with cohort
                const createResult = await repository.createPerson(
                    timestamp,
                    { name: 'Nested User' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, 'nested-tx'),
                    [{ distinctId: 'nested-tx', version: 0 }]
                )
                expect(createResult.success).toBe(true)

                // Add cohort within same transaction context (simulated)
                await postgres.query(
                    PostgresUse.PERSONS_WRITE,
                    'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                    [200, createResult.person.id, team.id],
                    'add-nested-cohort-primary'
                )
                await migrationPostgres.query(
                    PostgresUse.PERSONS_WRITE,
                    'INSERT INTO posthog_cohortpeople (cohort_id, person_id, team_id) VALUES ($1, $2, $3)',
                    [200, createResult.person.id, team.id],
                    'add-nested-cohort-secondary'
                )

                // Verify nested transaction completed successfully
                const primaryNested = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT p.uuid, cp.cohort_id FROM posthog_person p JOIN posthog_cohortpeople cp ON p.id = cp.person_id WHERE p.team_id = $1',
                    [team.id],
                    'verify-primary-nested'
                )
                const secondaryNested = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT p.uuid, cp.cohort_id FROM posthog_person p JOIN posthog_cohortpeople cp ON p.id = cp.person_id WHERE p.team_id = $1',
                    [team.id],
                    'verify-secondary-nested'
                )

                expect(primaryNested.rows.length).toBe(1)
                expect(primaryNested.rows[0].uuid).toBe(createResult.person.uuid)
                expect(primaryNested.rows[0].cohort_id).toBe(200)
                expect(secondaryNested.rows).toEqual(primaryNested.rows)
            })
        })
    })

    describe('Edge Cases', () => {
        describe('Concurrent operations', () => {
            it('handles concurrent merges gracefully', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-11T10:00:00.000Z').toUTC()

                // Create three persons for concurrent merge test
                const person1Result = await repository.createPerson(
                    timestamp,
                    { name: 'Concurrent User 1' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, 'concurrent-1'),
                    [{ distinctId: 'concurrent-1', version: 0 }]
                )
                const person2Result = await repository.createPerson(
                    timestamp,
                    { name: 'Concurrent User 2' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, 'concurrent-2'),
                    [{ distinctId: 'concurrent-2', version: 0 }]
                )
                const person3Result = await repository.createPerson(
                    timestamp,
                    { name: 'Concurrent User 3' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, 'concurrent-3'),
                    [{ distinctId: 'concurrent-3', version: 0 }]
                )

                expect(person1Result.success && person2Result.success && person3Result.success).toBe(true)

                // Simulate concurrent merges (in sequence since we can't do true concurrency in tests)
                const merge1Service = personMergeServiceDual({
                    team,
                    distinctId: 'concurrent-2',
                    event: '$identify',
                    timestamp,
                    properties: { $anon_distinct_id: 'concurrent-1' },
                })

                const [mergedPerson1, acks1] = await merge1Service.handleIdentifyOrAlias()
                expect(mergedPerson1).toBeDefined()
                await flushPersonStoreToKafka(hub, merge1Service.getContext().personStore, acks1)

                // Second merge should handle the already-merged state gracefully
                const merge2Service = personMergeServiceDual({
                    team,
                    distinctId: 'concurrent-3',
                    event: '$identify',
                    timestamp,
                    properties: { $anon_distinct_id: 'concurrent-2' },
                })

                const [mergedPerson2, acks2] = await merge2Service.handleIdentifyOrAlias()
                expect(mergedPerson2).toBeDefined()
                await flushPersonStoreToKafka(hub, merge2Service.getContext().personStore, acks2)

                // Verify final state: should have fewer persons than we started with (merges occurred)
                const primaryPersons = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-primary-concurrent-persons'
                )
                const secondaryPersons = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-concurrent-persons'
                )

                // Should have fewer than 3 persons (some merging occurred)
                expect(Number(primaryPersons.rows[0].count)).toBeLessThan(3)
                expect(Number(secondaryPersons.rows[0].count)).toBeLessThan(3)
                // Both DBs should have same count
                expect(Number(primaryPersons.rows[0].count)).toBe(Number(secondaryPersons.rows[0].count))

                const primaryDistincts = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                    [team.id],
                    'verify-primary-concurrent-distincts'
                )
                const secondaryDistincts = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_persondistinctid WHERE team_id = $1',
                    [team.id],
                    'verify-secondary-concurrent-distincts'
                )

                expect(Number(primaryDistincts.rows[0].count)).toBe(3)
                expect(Number(secondaryDistincts.rows[0].count)).toBe(3)
            })

            it('handles concurrent creates with same UUID', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-11T11:00:00.000Z').toUTC()
                const distinctId = 'uuid-collision'
                const uuid = uuidFromDistinctId(team.id, distinctId)

                // First create should succeed
                const firstResult = await repository.createPerson(
                    timestamp,
                    { name: 'First UUID User' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuid,
                    [{ distinctId, version: 0 }]
                )
                expect(firstResult.success).toBe(true)

                // Second create with same UUID should fail due to primary key constraint
                await expect(
                    repository.createPerson(
                        timestamp,
                        { name: 'Second UUID User' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuid,
                        [{ distinctId, version: 0 }]
                    )
                ).rejects.toThrow()

                // Verify only one person exists in both DBs
                const primaryPersons = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuid],
                    'verify-primary-uuid-collision'
                )
                const secondaryPersons = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT COUNT(*) FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuid],
                    'verify-secondary-uuid-collision'
                )

                expect(Number(primaryPersons.rows[0].count)).toBe(1)
                expect(Number(secondaryPersons.rows[0].count)).toBe(1)

                // Verify both DBs have same state
                const primaryPerson = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid, properties FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuid],
                    'get-primary-collision-person'
                )
                const secondaryPerson = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid, properties FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuid],
                    'get-secondary-collision-person'
                )

                expect(secondaryPerson.rows).toEqual(primaryPerson.rows)
            })
        })

        describe('Large property sets', () => {
            it('handles property size limit violations', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-11T12:00:00.000Z').toUTC()
                const distinctId = 'large-props'

                // Create extremely large properties
                const largeProperties: Record<string, string> = {}
                for (let i = 0; i < 5000; i++) {
                    largeProperties[`prop_${i}`] = 'x'.repeat(1000)
                }

                let createResult: any
                let createError: any

                try {
                    createResult = await repository.createPerson(
                        timestamp,
                        largeProperties,
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuidFromDistinctId(team.id, distinctId),
                        [{ distinctId, version: 0 }]
                    )
                } catch (error) {
                    createError = error
                }

                if (createError) {
                    // If creation failed, verify no partial data exists in either DB
                    const primaryPerson = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, uuidFromDistinctId(team.id, distinctId)],
                        'verify-primary-large-props-failed'
                    )
                    const secondaryPerson = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, uuidFromDistinctId(team.id, distinctId)],
                        'verify-secondary-large-props-failed'
                    )

                    expect(primaryPerson.rows.length).toBe(0)
                    expect(secondaryPerson.rows.length).toBe(0)
                } else if (createResult) {
                    // If creation succeeded, verify consistency
                    expect(createResult.success).toBe(true)

                    const primaryPerson = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, createResult.person.uuid],
                        'verify-primary-large-props-success'
                    )
                    const secondaryPerson = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, createResult.person.uuid],
                        'verify-secondary-large-props-success'
                    )

                    expect(primaryPerson.rows.length).toBe(1)
                    expect(secondaryPerson.rows.length).toBe(1)
                }
            })

            it('trims properties consistently across DBs', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-11T13:00:00.000Z').toUTC()
                const distinctId = 'trim-props'

                // Create properties that might need trimming
                const createResult = await repository.createPerson(
                    timestamp,
                    {
                        name: 'User with long properties',
                        longString: 'x'.repeat(10000), // Very long string
                        normalString: 'normal value',
                    },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, distinctId),
                    [{ distinctId, version: 0 }]
                )

                if (createResult.success) {
                    // Verify properties are identical in both DBs (either both trimmed or both full)
                    const primaryProps = await postgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT properties FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, createResult.person.uuid],
                        'get-primary-trimmed-props'
                    )
                    const secondaryProps = await migrationPostgres.query(
                        PostgresUse.PERSONS_READ,
                        'SELECT properties FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                        [team.id, createResult.person.uuid],
                        'get-secondary-trimmed-props'
                    )

                    expect(secondaryProps.rows[0].properties).toEqual(primaryProps.rows[0].properties)
                    expect(primaryProps.rows[0].properties.normalString).toBe('normal value')
                }
            })
        })

        describe('Error recovery', () => {
            it('cleans up prepared transactions on timeout', async () => {
                // This test would need to simulate transaction timeouts
                // For now, we just verify there are no lingering prepared transactions
                const primaryPrepared = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    `SELECT COUNT(*) FROM pg_prepared_xacts WHERE gid LIKE 'dualwrite:%'`,
                    [],
                    'check-primary-prepared-txs'
                )
                const secondaryPrepared = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    `SELECT COUNT(*) FROM pg_prepared_xacts WHERE gid LIKE 'dualwrite:%'`,
                    [],
                    'check-secondary-prepared-txs'
                )

                // Should be 0 prepared transactions lingering
                expect(Number(primaryPrepared.rows[0].count)).toBe(0)
                expect(Number(secondaryPrepared.rows[0].count)).toBe(0)
            })

            it('handles DB connection failures gracefully', async () => {
                const team = await getFirstTeam(hub)
                const timestamp = DateTime.fromISO('2024-02-11T14:00:00.000Z').toUTC()
                const distinctId = 'connection-failure'

                // Simulate connection failure by mocking query to throw specific error
                const spy = jest
                    .spyOn((repository as any).secondaryRepo, 'createPerson')
                    .mockRejectedValue(new Error('connection terminated unexpectedly'))

                await expect(
                    repository.createPerson(
                        timestamp,
                        { name: 'Connection Test User' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuidFromDistinctId(team.id, distinctId),
                        [{ distinctId, version: 0 }]
                    )
                ).rejects.toThrow('connection terminated unexpectedly')
                spy.mockRestore()

                // Verify no partial data exists
                const primaryPerson = await postgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuidFromDistinctId(team.id, distinctId)],
                    'verify-primary-connection-failure'
                )
                const secondaryPerson = await migrationPostgres.query(
                    PostgresUse.PERSONS_READ,
                    'SELECT uuid FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                    [team.id, uuidFromDistinctId(team.id, distinctId)],
                    'verify-secondary-connection-failure'
                )

                expect(primaryPerson.rows.length).toBe(0)
                expect(secondaryPerson.rows.length).toBe(0)
            })
        })
    })

    describe('Data Consistency Validation', () => {
        it('verifies identical final state across both DBs after operations', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-12T10:00:00.000Z').toUTC()

            // Perform a series of operations
            const person1Result = await repository.createPerson(
                timestamp,
                { name: 'Consistency User 1', initial: 'value1' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, 'consistency-1'),
                [{ distinctId: 'consistency-1', version: 0 }]
            )

            const person2Result = await repository.createPerson(
                timestamp,
                { name: 'Consistency User 2', initial: 'value2' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, 'consistency-2'),
                [{ distinctId: 'consistency-2', version: 0 }]
            )

            expect(person1Result.success && person2Result.success).toBe(true)

            // Update properties using updatePerson with proper InternalPerson updates
            await repository.updatePerson(
                person1Result.person,
                { properties: { ...person1Result.person.properties, updated: 'new value' } },
                'update-props'
            )

            // Merge persons
            const mergeService = personMergeServiceDual({
                team,
                distinctId: 'consistency-2',
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: 'consistency-1' },
            })

            const [mergedPerson, acks] = await mergeService.handleIdentifyOrAlias()
            expect(mergedPerson).toBeDefined()
            await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

            // Verify identical final state
            const primaryFinal = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT p.uuid, p.properties, p.is_identified, p.version, pd.distinct_id, pd.version as pdi_version FROM posthog_person p JOIN posthog_persondistinctid pd ON p.id = pd.person_id WHERE p.team_id = $1 ORDER BY pd.distinct_id',
                [team.id],
                'get-primary-final-state'
            )
            const secondaryFinal = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT p.uuid, p.properties, p.is_identified, p.version, pd.distinct_id, pd.version as pdi_version FROM posthog_person p JOIN posthog_persondistinctid pd ON p.id = pd.person_id WHERE p.team_id = $1 ORDER BY pd.distinct_id',
                [team.id],
                'get-secondary-final-state'
            )

            expect(secondaryFinal.rows).toEqual(primaryFinal.rows)
        })

        it('validates version consistency across merges', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-12T11:00:00.000Z').toUTC()

            // Create persons with specific versions
            const person1Result = await repository.createPerson(
                timestamp,
                { name: 'Version User 1' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, 'version-1'),
                [{ distinctId: 'version-1', version: 0 }]
            )

            // Add personless distinct ID
            await repository.addPersonlessDistinctId(team.id, 'version-personless')

            const person2Result = await repository.createPerson(
                timestamp,
                { name: 'Version User 2' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, 'version-2'),
                [{ distinctId: 'version-2', version: 0 }]
            )

            expect(person1Result.success && person2Result.success).toBe(true)

            // Merge with personless
            const mergeService = personMergeServiceDual({
                team,
                distinctId: 'version-personless',
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: 'version-1' },
            })

            const [mergedPerson, acks] = await mergeService.handleIdentifyOrAlias()
            expect(mergedPerson).toBeDefined()
            await flushPersonStoreToKafka(hub, mergeService.getContext().personStore, acks)

            // Verify version consistency
            const primaryVersions = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT distinct_id, version FROM posthog_persondistinctid WHERE team_id = $1 ORDER BY distinct_id',
                [team.id],
                'get-primary-versions'
            )
            const secondaryVersions = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT distinct_id, version FROM posthog_persondistinctid WHERE team_id = $1 ORDER BY distinct_id',
                [team.id],
                'get-secondary-versions'
            )

            expect(secondaryVersions.rows).toEqual(primaryVersions.rows)

            // Verify version logic is correct
            const versionMap = primaryVersions.rows.reduce((acc: any, row: any) => {
                acc[row.distinct_id] = Number(row.version)
                return acc
            }, {})

            expect(versionMap['version-1']).toBe(0) // Original
            expect(versionMap['version-personless']).toBe(1) // Was personless
            expect(versionMap['version-2']).toBe(0) // Original
        })

        it('ensures distinct ID mappings are identical', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-12T12:00:00.000Z').toUTC()

            // Create complex scenario with multiple merges
            const distinctIds = ['mapping-1', 'mapping-2', 'mapping-3', 'mapping-4']
            const persons = []

            for (const distinctId of distinctIds) {
                const result = await repository.createPerson(
                    timestamp,
                    { name: `Mapping User ${distinctId}` },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuidFromDistinctId(team.id, distinctId),
                    [{ distinctId, version: 0 }]
                )
                expect(result.success).toBe(true)
                persons.push(result.person)
            }

            // Perform multiple merges
            const merge1 = personMergeServiceDual({
                team,
                distinctId: 'mapping-2',
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: 'mapping-1' },
            })

            const [_merged1, acks1] = await merge1.handleIdentifyOrAlias()
            await flushPersonStoreToKafka(hub, merge1.getContext().personStore, acks1)

            const merge2 = personMergeServiceDual({
                team,
                distinctId: 'mapping-4',
                event: '$identify',
                timestamp,
                properties: { $anon_distinct_id: 'mapping-3' },
            })

            const [_merged2, acks2] = await merge2.handleIdentifyOrAlias()
            await flushPersonStoreToKafka(hub, merge2.getContext().personStore, acks2)

            // Verify mappings are identical
            const primaryMappings = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT pd.distinct_id, p.uuid FROM posthog_persondistinctid pd JOIN posthog_person p ON pd.person_id = p.id WHERE pd.team_id = $1 ORDER BY pd.distinct_id',
                [team.id],
                'get-primary-mappings'
            )
            const secondaryMappings = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT pd.distinct_id, p.uuid FROM posthog_persondistinctid pd JOIN posthog_person p ON pd.person_id = p.id WHERE pd.team_id = $1 ORDER BY pd.distinct_id',
                [team.id],
                'get-secondary-mappings'
            )

            expect(secondaryMappings.rows).toEqual(primaryMappings.rows)
        })

        it('confirms property states match exactly', async () => {
            const team = await getFirstTeam(hub)
            const timestamp = DateTime.fromISO('2024-02-12T13:00:00.000Z').toUTC()

            // Create person with complex properties
            const createResult = await repository.createPerson(
                timestamp,
                {
                    name: 'Property Test User',
                    number: 42,
                    boolean: true,
                    array: [1, 2, 3],
                    object: { nested: 'value' },
                    string: 'test',
                },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, 'property-test'),
                [{ distinctId: 'property-test', version: 0 }]
            )
            expect(createResult.success).toBe(true)

            // Update with new properties (simulating property updates)
            const { boolean, ...propsWithoutBoolean } = createResult.person.properties
            await repository.updatePerson(
                createResult.person,
                {
                    properties: {
                        ...propsWithoutBoolean,
                        newProp: 'new',
                        number: 100,
                        onceProp: 'once',
                        // Note: boolean explicitly removed to simulate $unset, name preserved to simulate $set_once behavior
                    },
                },
                'update-mixed-props'
            )

            // Verify exact property matching
            const primaryProps = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, createResult.person.uuid],
                'get-primary-props'
            )
            const secondaryProps = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, createResult.person.uuid],
                'get-secondary-props'
            )

            expect(secondaryProps.rows[0].properties).toEqual(primaryProps.rows[0].properties)

            // Verify specific property operations worked correctly
            const properties = primaryProps.rows[0].properties
            expect(properties).toMatchObject({
                name: 'Property Test User', // preserved
                number: 100, // updated
                array: [1, 2, 3], // preserved
                object: { nested: 'value' }, // preserved
                string: 'test', // preserved
                newProp: 'new', // added
                onceProp: 'once', // added
            })
            expect(properties).not.toHaveProperty('boolean') // removed
        })
    })

    it('mergePeople commits across both primary and secondary inside 2PC', async () => {
        const team = await getFirstTeam(hub)
        const createdAt = DateTime.fromISO('2024-02-01T10:30:00.000Z').toUTC()

        const sourceDistinct = 'dw-src'
        const targetDistinct = 'dw-tgt'
        const srcUuid = uuidFromDistinctId(team.id, sourceDistinct)
        const tgtUuid = uuidFromDistinctId(team.id, targetDistinct)

        // create two persons via dual write repo (also 2pc, but focus is merge 2pc)
        const src = await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, srcUuid, [
            { distinctId: sourceDistinct, version: 0 },
        ])
        const tgt = await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, tgtUuid, [
            { distinctId: targetDistinct, version: 0 },
        ])
        expect(src.success && tgt.success).toBe(true)

        //merge with properties update inside inTransaction('mergePeople')
        const svc = personMergeServiceDual({
            team,
            distinctId: targetDistinct,
            event: '$identify',
            timestamp: createdAt,
            properties: { $anon_distinct_id: sourceDistinct, $set: { merged: true } },
        })

        const [person, acks] = await svc.handleIdentifyOrAlias()
        const ctx = svc.getContext()
        await flushPersonStoreToKafka(hub, ctx.personStore, acks)
        // Primary: one remaining person, has both distinct IDs, properties updated, is_identified true
        const pPerson = await postgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid, properties, is_identified FROM posthog_person WHERE team_id = $1 ORDER BY id',
            [team.id],
            'verify-primary-merge'
        )
        expect(pPerson.rows.length).toBe(1)
        expect(pPerson.rows[0].uuid === tgtUuid || pPerson.rows[0].uuid === srcUuid).toBe(true)
        expect(pPerson.rows[0].is_identified).toBe(true)
        expect(pPerson.rows[0].properties).toMatchObject({ merged: true })

        const pDistinct = await postgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
            [pPerson.rows[0].id],
            'verify-primary-merge-distinct'
        )
        expect(pDistinct.rows.map((r: any) => r.distinct_id).sort()).toEqual([sourceDistinct, targetDistinct].sort())

        // Secondary: same final state
        const sPerson = await migrationPostgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid, properties, is_identified FROM posthog_person WHERE team_id = $1 ORDER BY id',
            [team.id],
            'verify-secondary-merge'
        )
        expect(sPerson.rows.length).toBe(1)
        expect(sPerson.rows[0].uuid === tgtUuid || sPerson.rows[0].uuid === srcUuid).toBe(true)
        expect(sPerson.rows[0].is_identified).toBe(true)
        expect(sPerson.rows[0].properties).toMatchObject({ merged: true })

        const sDistinct = await migrationPostgres.query(
            PostgresUse.PERSONS_READ,
            `SELECT pd.distinct_id
             FROM posthog_persondistinctid pd
             WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2)
             ORDER BY distinct_id`,
            [team.id, sPerson.rows[0].uuid],
            'verify-secondary-merge-distinct'
        )
        expect(sDistinct.rows.map((r: any) => r.distinct_id).sort()).toEqual([sourceDistinct, targetDistinct].sort())

        // Returned person should match the surviving one
        expect(person).toMatchObject<Partial<InternalPerson>>({
            uuid: sPerson.rows[0].uuid,
            is_identified: true,
            properties: { merged: true },
        })
    })

    it('rolls back both databases when primary database fails during merge', async () => {
        const team = await getFirstTeam(hub)
        const timestamp = DateTime.fromISO('2024-02-01T10:30:00.000Z').toUTC()

        const firstUserDistinctId = 'first'
        const secondUserDistinctId = 'second'
        const firstUserUuid = uuidFromDistinctId(team.id, firstUserDistinctId)
        const secondUserUuid = uuidFromDistinctId(team.id, secondUserDistinctId)

        // Create persons in both databases
        const firstResult = await repository.createPerson(timestamp, {}, {}, {}, team.id, null, false, firstUserUuid, [
            { distinctId: firstUserDistinctId },
        ])
        const secondResult = await repository.createPerson(
            timestamp,
            {},
            {},
            {},
            team.id,
            null,
            false,
            secondUserUuid,
            [{ distinctId: secondUserDistinctId }]
        )

        expect(firstResult.success && secondResult.success).toBe(true)
        if (!firstResult.success || !secondResult.success) {
            throw new Error('Failed to create test persons')
        }

        const first = firstResult.person
        const second = secondResult.person

        // Mock primary database to fail during merge
        const originalQuery = postgres.query.bind(postgres)
        jest.spyOn(postgres, 'query').mockImplementation(async (use, query, params, tag) => {
            // Handle both string and QueryConfig types
            const queryString = typeof query === 'string' ? query : query.text
            const queryTag = typeof tag === 'string' ? tag : ''

            // Fail specific merge operations
            if (
                (queryString.includes('UPDATE posthog_person') && queryTag.includes('updatePerson')) ||
                (queryString.includes('UPDATE posthog_persondistinctid') && queryTag.includes('updateDistinctIdPerson'))
            ) {
                throw new Error('Simulated primary database failure')
            }
            return originalQuery(use, query, params, tag)
        })

        const mergeService = personMergeServiceDual({
            team,
            distinctId: secondUserDistinctId,
            event: '$identify',
            timestamp,
            properties: { $anon_distinct_id: firstUserDistinctId },
        })

        // Merge should fail and throw error
        await expect(
            mergeService.mergePeople({
                mergeInto: first,
                mergeIntoDistinctId: firstUserDistinctId,
                otherPerson: second,
                otherPersonDistinctId: secondUserDistinctId,
            })
        ).rejects.toThrow('Simulated primary database failure')

        // Verify both databases still have original state (rollback worked)
        const primaryPersons = await postgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid, properties, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
            [team.id],
            'verify-primary-rollback'
        )
        expect(primaryPersons.rows.length).toEqual(2)
        expect(primaryPersons.rows[0]).toMatchObject({
            uuid: firstUserUuid,
            is_identified: false,
            version: '0',
        })
        expect(primaryPersons.rows[1]).toMatchObject({
            uuid: secondUserUuid,
            is_identified: false,
            version: '0',
        })

        const secondaryPersons = await migrationPostgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid, properties, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
            [team.id],
            'verify-secondary-rollback'
        )
        expect(secondaryPersons.rows.length).toEqual(2)
        expect(secondaryPersons.rows[0]).toMatchObject({
            uuid: firstUserUuid,
            is_identified: false,
            version: '0',
        })
        expect(secondaryPersons.rows[1]).toMatchObject({
            uuid: secondUserUuid,
            is_identified: false,
            version: '0',
        })

        // Both databases should have identical state
        expect(primaryPersons.rows).toEqual(secondaryPersons.rows)
    })

    it('rolls back both databases when secondary database fails during merge', async () => {
        const team = await getFirstTeam(hub)
        const timestamp = DateTime.fromISO('2024-02-01T10:30:00.000Z').toUTC()

        const firstUserDistinctId = 'first'
        const secondUserDistinctId = 'second'
        const firstUserUuid = uuidFromDistinctId(team.id, firstUserDistinctId)
        const secondUserUuid = uuidFromDistinctId(team.id, secondUserDistinctId)

        // Create persons in both databases
        const firstResult = await repository.createPerson(timestamp, {}, {}, {}, team.id, null, false, firstUserUuid, [
            { distinctId: firstUserDistinctId },
        ])
        const secondResult = await repository.createPerson(
            timestamp,
            {},
            {},
            {},
            team.id,
            null,
            false,
            secondUserUuid,
            [{ distinctId: secondUserDistinctId }]
        )

        expect(firstResult.success && secondResult.success).toBe(true)
        if (!firstResult.success || !secondResult.success) {
            throw new Error('Failed to create test persons')
        }

        const first = firstResult.person
        const second = secondResult.person

        // Mock secondary database to fail during merge
        const originalQuery = migrationPostgres.query.bind(migrationPostgres)
        jest.spyOn(migrationPostgres, 'query').mockImplementation(async (use, query, params, tag) => {
            // Handle both string and QueryConfig types
            const queryString = typeof query === 'string' ? query : query.text
            const queryTag = typeof tag === 'string' ? tag : ''

            // Fail specific merge operations
            if (
                (queryString.includes('UPDATE posthog_person') && queryTag.includes('updatePerson')) ||
                (queryString.includes('UPDATE posthog_persondistinctid') && queryTag.includes('updateDistinctIdPerson'))
            ) {
                throw new Error('Simulated secondary database failure')
            }
            return originalQuery(use, query, params, tag)
        })

        const mergeService = personMergeServiceDual({
            team,
            distinctId: secondUserDistinctId,
            event: '$identify',
            timestamp,
            properties: { $anon_distinct_id: firstUserDistinctId },
        })

        // Merge should fail and throw error
        await expect(
            mergeService.mergePeople({
                mergeInto: first,
                mergeIntoDistinctId: firstUserDistinctId,
                otherPerson: second,
                otherPersonDistinctId: secondUserDistinctId,
            })
        ).rejects.toThrow('Simulated secondary database failure')

        // Verify both databases still have original state (rollback worked)
        const primaryPersons = await postgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid, properties, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
            [team.id],
            'verify-primary-rollback'
        )
        expect(primaryPersons.rows.length).toEqual(2)
        expect(primaryPersons.rows[0]).toMatchObject({
            uuid: firstUserUuid,
            is_identified: false,
            version: '0',
        })
        expect(primaryPersons.rows[1]).toMatchObject({
            uuid: secondUserUuid,
            is_identified: false,
            version: '0',
        })

        const secondaryPersons = await migrationPostgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid, properties, is_identified, version FROM posthog_person WHERE team_id = $1 ORDER BY id',
            [team.id],
            'verify-secondary-rollback'
        )
        expect(secondaryPersons.rows.length).toEqual(2)
        expect(secondaryPersons.rows[0]).toMatchObject({
            uuid: firstUserUuid,
            is_identified: false,
            version: '0',
        })
        expect(secondaryPersons.rows[1]).toMatchObject({
            uuid: secondUserUuid,
            is_identified: false,
            version: '0',
        })

        // Both databases should have identical state
        expect(primaryPersons.rows).toEqual(secondaryPersons.rows)
    })

    it('rolls back both databases when primary database fails during person creation', async () => {
        const team = await getFirstTeam(hub)
        const timestamp = DateTime.fromISO('2024-02-01T10:30:00.000Z').toUTC()

        const distinctId = 'test-user'
        const userUuid = uuidFromDistinctId(team.id, distinctId)

        // Mock primary database to fail during person creation
        const originalQuery = postgres.query.bind(postgres)
        jest.spyOn(postgres, 'query').mockImplementation(async (use, query, params, tag) => {
            // Handle both string and QueryConfig types
            const queryString = typeof query === 'string' ? query : query.text
            const queryTag = typeof tag === 'string' ? tag : ''

            // Fail person insertion
            if (queryString.includes('INSERT INTO posthog_person') && queryTag.includes('insertPerson')) {
                throw new Error('Simulated primary database failure during creation')
            }
            return originalQuery(use, query, params, tag)
        })

        // Person creation should fail and throw error
        await expect(
            repository.createPerson(timestamp, { name: 'Test User' }, {}, {}, team.id, null, false, userUuid, [
                { distinctId },
            ])
        ).rejects.toThrow('Simulated primary database failure during creation')

        // Verify no person was created in either database (rollback worked)
        const primaryPersons = await postgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid FROM posthog_person WHERE team_id = $1',
            [team.id],
            'verify-primary-no-creation'
        )
        expect(primaryPersons.rows.length).toEqual(0)

        const secondaryPersons = await migrationPostgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid FROM posthog_person WHERE team_id = $1',
            [team.id],
            'verify-secondary-no-creation'
        )
        expect(secondaryPersons.rows.length).toEqual(0)
    })

    it('rolls back both databases when secondary database fails during person creation', async () => {
        const team = await getFirstTeam(hub)
        const timestamp = DateTime.fromISO('2024-02-01T10:30:00.000Z').toUTC()

        const distinctId = 'test-user'
        const userUuid = uuidFromDistinctId(team.id, distinctId)

        // Mock secondary database to fail during person creation
        const originalQuery = migrationPostgres.query.bind(migrationPostgres)
        jest.spyOn(migrationPostgres, 'query').mockImplementation(async (use, query, params, tag) => {
            // Handle both string and QueryConfig types
            const queryString = typeof query === 'string' ? query : query.text
            const queryTag = typeof tag === 'string' ? tag : ''

            // Fail person insertion
            if (queryString.includes('INSERT INTO posthog_person') && queryTag.includes('insertPerson')) {
                throw new Error('Simulated secondary database failure during creation')
            }
            return originalQuery(use, query, params, tag)
        })

        // Person creation should fail and throw error
        await expect(
            repository.createPerson(timestamp, { name: 'Test User' }, {}, {}, team.id, null, false, userUuid, [
                { distinctId },
            ])
        ).rejects.toThrow('Simulated secondary database failure during creation')

        // Verify no person was created in either database (rollback worked)
        const primaryPersons = await postgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid FROM posthog_person WHERE team_id = $1',
            [team.id],
            'verify-primary-no-creation'
        )
        expect(primaryPersons.rows.length).toEqual(0)

        const secondaryPersons = await migrationPostgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT id, uuid FROM posthog_person WHERE team_id = $1',
            [team.id],
            'verify-secondary-no-creation'
        )
        expect(secondaryPersons.rows.length).toEqual(0)
    })
})
