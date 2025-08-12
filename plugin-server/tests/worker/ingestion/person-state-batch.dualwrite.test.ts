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
            await migrationPostgres.query(
                PostgresUse.PERSONS_WRITE,
                `DROP TABLE IF EXISTS ${table} CASCADE`,
                [],
                `drop-${table}`
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
