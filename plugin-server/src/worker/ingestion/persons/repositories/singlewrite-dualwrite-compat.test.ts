// for testing scenarios and ensuring that outcomes for dualwrite and singlewrite are the same

// we should test: 1. contract returned is the same, 2. consistency across primary and secondary
import fs from 'fs'
import { DateTime } from 'luxon'
import path from 'path'

import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'
import { InternalPerson } from '~/types'
import { TopicMessage } from '~/kafka/producer'

import { PostgresDualWritePersonRepository } from './postgres-dualwrite-person-repository'
import { PersonPropertiesSizeViolationError } from './person-repository'
import { uuidFromDistinctId } from '../../person-uuid'
import { UUIDT } from '~/utils/utils'
import { CreatePersonResult } from  '../../../../utils/db/db'
import { PostgresPersonRepository } from './postgres-person-repository'

jest.mock('../../../../utils/logger')

describe('Postgres Single Write - Postgres Dual Write Compatibility', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let dualWriteRepository: PostgresDualWritePersonRepository
    let singleWriteRepository: PostgresPersonRepository

    async function setupMigrationDb(): Promise<void> {
        // Drop relevant tables to start clean, then re-create schema from SQL
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
        const sqlPath = path.resolve(__dirname, '../../../../../sql/create_persons_tables.sql')
        const sql = fs.readFileSync(sqlPath, 'utf8')
        // Apply to migration DB
        await migrationPostgres.query(PostgresUse.PERSONS_WRITE, sql, [], 'create-persons-schema-secondary')
        // Also ensure primary has minimal persons schema for tests if it's missing
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

    // helper function to get the first team in the database
    async function getFirstTeam(postgres: PostgresRouter): Promise<Team> {
        const teams = await postgres.query(
            PostgresUse.COMMON_WRITE,
            'SELECT * FROM posthog_team LIMIT 1',
            [],
            'getFirstTeam'
        )
        return teams.rows[0]
    }

    // helper function to assert consistency between primary and secondary after some db operation
    async function assertConsistencyAcrossDatabases(
        primaryRotuer: PostgresRouter,
        secondaryRouter: PostgresRouter,
        query: string,
        params: any[],
        primaryTag: string,
        secondaryTag: string
    ) {
        const [primary, secondary] = await Promise.all([
            primaryRotuer.query(PostgresUse.PERSONS_READ, query, params, primaryTag),
            secondaryRouter.query(PostgresUse.PERSONS_READ, query, params, secondaryTag)
        ])
        expect(primary.rows).toEqual(secondary.rows)
    }



    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        migrationPostgres = hub.db.postgresPersonMigration
        await setupMigrationDb()

        dualWriteRepository = new PostgresDualWritePersonRepository(postgres, migrationPostgres)
        singleWriteRepository = new PostgresPersonRepository(postgres)

        // NICKS TODO: do we need this?
        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)
    })

    afterEach(async () => {
        await cleanupPrepared(hub)
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('createPerson() is compatible between single and dual write and consistent between primary and secondary', () => {

        function assertCreatePersonContractParity(singleResult: CreatePersonResult, dualResult: CreatePersonResult) {
            expect(singleResult.success).toBe(true)
            expect(dualResult.success).toBe(true)

            // There is a lint problem here due to the whackiness of the CreatePersonResult type
            // We return a different result when the database fails but we catch it
            expect(singleResult.person.properties).toEqual(dualResult.person.properties)
        }

        function assertCreatePersonConflictContractParity(singleResult: CreatePersonResult, dualResult: CreatePersonResult) {
            expect(singleResult.success).toBe(false)
            expect(dualResult.success).toBe(false)
            expect(singleResult.error).toBe(dualResult.error)
            expect(singleResult.distinctIds).toEqual(dualResult.distinctIds)
        }

        it('happy path createPerson()', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            const uuid2 = '22222222-2222-2222-2222-222222222222'

            const singleResult = await singleWriteRepository.createPerson(
                createdAt,
                { name: 'Bob' },
                {},
                {},
                team.id,
                null,
                true,
                uuid,
                [{ distinctId: 'single-a', version: 0 }]
            )

            const dualResult = await dualWriteRepository.createPerson(
                createdAt,
                { name: 'Bob' },
                {},
                {},
                team.id,
                null,
                true,
                uuid2,
                [{ distinctId: 'dual-a', version: 0 }]
            )

            assertCreatePersonContractParity(singleResult, dualResult)

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid2],
                'verify-primary-create',
                'verify-secondary-create'
            )
        })

        it('createPerson() PersonPropertiesSizeViolation', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'

            const spy = jest
                .spyOn((singleWriteRepository as any), 'createPerson')
                .mockRejectedValue(new PersonPropertiesSizeViolationError('too big', team.id, undefined))

            const dualSpy = jest
                .spyOn((dualWriteRepository as any).primaryRepo, 'createPerson')
                .mockRejectedValue(new PersonPropertiesSizeViolationError('too big', team.id, undefined))

            // Single write throws; contract is the same
            await expect(singleWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'single-a', version: 0 }])).rejects.toThrow(PersonPropertiesSizeViolationError)

            spy.mockRestore()
            // Dual write throws; contract is the same
            await expect(dualWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'dual-a', version: 0 }])).rejects.toThrow(PersonPropertiesSizeViolationError)
            dualSpy.mockRestore()

            // Database results are consistent
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-create',
                'verify-secondary-create'
            )
        })
        it('createPerson() CreationConflict', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const distinctId = 'primary-conflict-distinct'

            // seed the primary database with a person with the above distinctId
            const seedP = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `
                WITH p AS (
                    INSERT INTO posthog_person (
                        created_at, properties, properties_last_updated_at, properties_last_operation,
                        team_id, is_user_id, is_identified, uuid, version
                    )
                    VALUES (now(), '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, $1, NULL, false, $2, 0)
                    RETURNING id
                )
                INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                SELECT $3, p.id, $1, 0 FROM p
                RETURNING person_id`,
                [team.id, new UUIDT().toString(), distinctId],
                'seed-primary-pdi-conflict'
            )
            expect(seedP.rows.length).toBe(1)

            // both single and dual write should conflict when we try to create a person with the same distinctId
            const singleResult = await singleWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuidFromDistinctId(team.id, distinctId), [{ distinctId, version: 0 }])
            const dualResult = await dualWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuidFromDistinctId(team.id, distinctId), [{ distinctId, version: 0 }])

            assertCreatePersonConflictContractParity(singleResult, dualResult)

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuidFromDistinctId(team.id, distinctId)],
                'verify-primary-create',
                'verify-secondary-create'
            )
        })
        it('createPerson() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'

            const spy = jest
                .spyOn((singleWriteRepository as any), 'createPerson')
                .mockRejectedValue(new Error('unhandled error'))

            const dualSpy = jest
                .spyOn((dualWriteRepository as any).primaryRepo, 'createPerson')
                .mockRejectedValue(new Error('unhandled error'))

            await expect(singleWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'single-a', version: 0 }])).rejects.toThrow(Error)
            spy.mockRestore()

            await expect(dualWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'dual-a', version: 0 }])).rejects.toThrow(Error)
            dualSpy.mockRestore()

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-create',
                'verify-secondary-create'
            )
        })
    })
    describe('updatePerson() is compatible between single and dual write and consistent between primary and secondary', () => {
        function assertUpdatePersonContractParity(singleResult: [InternalPerson, TopicMessage[], boolean], dualResult: [InternalPerson, TopicMessage[], boolean]) {
            expect(singleResult[0].properties).toEqual(dualResult[0].properties)
            expect(singleResult[1].properties).toEqual(dualResult[1].properties)
            expect(singleResult[2]).toEqual(dualResult[2])
        }
        it('happy path updatePerson()', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            const uuid2 = '22222222-2222-2222-2222-222222222222'

            const singleCreatePersonResult = await singleWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'single-a', version: 0 }])
            const dualCreatePersonResult = await dualWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid2, [{ distinctId: 'dual-a', version: 0 }])

            const singleUpdateResult = await singleWriteRepository.updatePerson(singleCreatePersonResult.person, { properties: { name: 'B' } }, 'single-update')
            const dualUpdateResult = await dualWriteRepository.updatePerson(dualCreatePersonResult.person, { properties: { name: 'B' } }, 'dual-update')
            assertUpdatePersonContractParity(singleUpdateResult, dualUpdateResult)
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid2],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        it('updatePerson() unhandled database error', async() => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            // NICKS TODO: change name/move these to the class or something
            const uuid2 = '22222222-2222-2222-2222-222222222222'

            const singleCreatePersonResult = await singleWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'single-a', version: 0 }])
            const dualCreatePersonResult = await dualWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid2, [{ distinctId: 'dual-a', version: 0 }])

            // NICKS TODO: we need to actually mock out the DB funciton call as an error not 
            // the updatePerson functionn
            // This isn't testing that the contract for single write and dual write are the same
            // because we are just mocking the updatePerson function
            // Similar updates to do for the other tests that use this method
            const spy = jest.spyOn((singleWriteRepository as any), 'updatePerson').mockRejectedValue(new Error('unhandled error'))
            const dualSpy = jest.spyOn((dualWriteRepository as any).primaryRepo, 'updatePerson').mockRejectedValue(new Error('unhandled error'))

            await expect(singleWriteRepository.updatePerson(singleCreatePersonResult.person, { properties: { name: 'B' } }, 'single-update')).rejects.toThrow(Error)
            spy.mockRestore()

            await expect(dualWriteRepository.updatePerson(dualCreatePersonResult.person, { properties: { name: 'B' } }, 'dual-update')).rejects.toThrow(Error)
            dualSpy.mockRestore()

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid2],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        // NICKS TODO: do this test and other PersonPropertiesSizeViolation (where create wasn't already over the limit)
        it('updatePerson() PersonPropertiesSizeViolation existing properties trimmed', async() => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            const uuid2 = '22222222-2222-2222-2222-222222222222'
        })
    })

    describe('deletePerson() is compatible between single and dual write and consistent between primary and secondary', () => {
        function assertDeletePersonContractParity(singleResult: TopicMessage[], dualResult: TopicMessage[]) {
            // asserts that the length of the kafka messages are the same
            expect(singleResult.length).toEqual(dualResult.length)
            expect(singleResult[0].topic).toEqual(dualResult[0].topic)
        }
        it('happy path deletePerson()', async() => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            const uuid2 = '22222222-2222-2222-2222-222222222222'

            const singleCreatePersonResult = await singleWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'single-a', version: 0 }])
            const dualCreatePersonResult = await dualWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid2, [{ distinctId: 'dual-a', version: 0 }])

            const singleDeleteResult = await singleWriteRepository.deletePerson(singleCreatePersonResult.person)
            const dualDeleteResult = await dualWriteRepository.deletePerson(dualCreatePersonResult.person)

            assertDeletePersonContractParity(singleDeleteResult, dualDeleteResult)

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid2],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
        it('deletePerson() unhandled database error', async() => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            const uuid2 = '22222222-2222-2222-2222-222222222222'
        })
        it('deletePerson() deadlock detected', async() => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            const uuid2 = '22222222-2222-2222-2222-222222222222'


            const singleCreatePersonResult = await singleWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [{ distinctId: 'single-a', version: 0 }])
            const dualCreatePersonResult = await dualWriteRepository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid2, [{ distinctId: 'dual-a', version: 0 }])

            const originalPrimaryQuery = postgres.query.bind(postgres)
            const primaryDeadlock = jest.spyOn(postgres, 'query').mockImplementation((use: any, text: any, params: any, tag: string) => {
                if (tag === 'deletePerson') {
                    const e: any = new Error('deadlock detected')
                    e.code = '40P01'
                    throw e
                }
                return originalPrimaryQuery(use, text, params, tag)
            })


            // if deadlock detected, we don't throw an error
            // NICKS TODO: update this so that is expecting to throw...
            // we log on deadlock but we also re-throw the error
            let singleDeleteResult = await singleWriteRepository.deletePerson(singleCreatePersonResult.person)
            let dualDeleteResult = await dualWriteRepository.deletePerson(dualCreatePersonResult.person)

            spy.mockRestore()
            dualSpy.mockRestore()
            console.log('singleDeleteResult', singleDeleteResult)
            console.log('dualDeleteResult', dualDeleteResult)

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid2],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
    })
})

