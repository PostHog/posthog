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
import { AnyTypeAnnotation } from '@babel/types'

jest.mock('../../../../utils/logger')

describe('Postgres Single Write - Postgres Dual Write Compatibility', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let dualWriteRepository: PostgresDualWritePersonRepository
    let singleWriteRepository: PostgresPersonRepository

    // Common test constants
    const TEST_UUIDS = {
        single: '11111111-1111-1111-1111-111111111111',
        dual: '22222222-2222-2222-2222-222222222222',
    }
    const TEST_TIMESTAMP = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

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

    // Helper to create persons in both repositories with consistent test data
    async function createPersonsInBothRepos(
        team: Team,
        properties: Record<string, any> = { name: 'A' },
        singleDistinctId: string = 'single-a',
        dualDistinctId: string = 'dual-a',
        createdAt: DateTime = TEST_TIMESTAMP,
        singleUuid: string = TEST_UUIDS.single,
        dualUuid: string = TEST_UUIDS.dual
    ) {
        const [singleResult, dualResult] = await Promise.all([
            singleWriteRepository.createPerson(
                createdAt,
                properties,
                {},
                {},
                team.id,
                null,
                false,
                singleUuid,
                [{ distinctId: singleDistinctId, version: 0 }]
            ),
            dualWriteRepository.createPerson(
                createdAt,
                properties,
                {},
                {},
                team.id,
                null,
                false,
                dualUuid,
                [{ distinctId: dualDistinctId, version: 0 }]
            )
        ])
        return { singleResult, dualResult }
    }

    // Helper to mock database errors for testing error handling consistency
    function mockDatabaseError(
        router: PostgresRouter,
        error: Error | { message: string; code?: string },
        tagPattern: string | RegExp
    ) {
        const originalQuery = router.query.bind(router)
        return jest.spyOn(router, 'query').mockImplementation((use: any, text: any, params: any, tag: string) => {
            const shouldThrow = typeof tagPattern === 'string' 
                ? tag && tag.startsWith(tagPattern)
                : tag && tagPattern.test(tag)
            
            if (shouldThrow) {
                if (error instanceof Error) {
                    throw error
                } else {
                    const e: any = new Error(error.message)
                    if (error.code) e.code = error.code
                    throw e
                }
            }
            return originalQuery(use, text, params, tag)
        })
    }

    // Helper to assert that both repositories throw similar
    // errors when encountering a database error
    async function assertConsistentDatabaseErrorHandling<T>(
        error: Error | { message: string; code?: string },
        tagPattern: string | RegExp,
        singleWriteOperation: () => Promise<T>,
        dualWriteOperation: () => Promise<T>,
        expectedError?: string | RegExp | typeof Error
    ) {
        // Test single write repository
        const singleSpy = mockDatabaseError(postgres, error, tagPattern)
        let singleError: any
        try {
            await singleWriteOperation()
        } catch (e) {
            singleError = e
        }
        singleSpy.mockRestore()

        // Test dual write repository
        const dualSpy = mockDatabaseError(postgres, error, tagPattern)
        let dualError: any
        try {
            await dualWriteOperation()
        } catch (e) {
            dualError = e
        }
        dualSpy.mockRestore()

        // Both should handle the error the same way
        if (expectedError) {
            expect(singleError).toBeDefined()
            expect(dualError).toBeDefined()
            
            if (typeof expectedError === 'string') {
                expect(singleError.message).toContain(expectedError)
                expect(dualError.message).toContain(expectedError)
            } else if (expectedError instanceof RegExp) {
                expect(singleError.message).toMatch(expectedError)
                expect(dualError.message).toMatch(expectedError)
            } else {
                expect(singleError).toBeInstanceOf(expectedError)
                expect(dualError).toBeInstanceOf(expectedError)
            }
        } else {
            // Both should throw the same error
            expect(singleError).toBeDefined()
            expect(dualError).toBeDefined()
            expect(singleError.message).toBe(dualError.message)
            if ((error as any).code) {
                expect(singleError.code).toBe((error as any).code)
                expect(dualError.code).toBe((error as any).code)
            }
        }
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
            
            const singleResult = await singleWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Bob' },
                {},
                {},
                team.id,
                null,
                true,
                TEST_UUIDS.single,
                [{ distinctId: 'single-a', version: 0 }]
            )

            const dualResult = await dualWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Bob' },
                {},
                {},
                team.id,
                null,
                true,
                TEST_UUIDS.dual,
                [{ distinctId: 'dual-a', version: 0 }]
            )

            assertCreatePersonContractParity(singleResult, dualResult)

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-create',
                'verify-secondary-create'
            )
        })

        it('createPerson() PersonPropertiesSizeViolation', async () => {
            const team = await getFirstTeam(postgres)

            const singleSpy = mockDatabaseError(postgres, new PersonPropertiesSizeViolationError('too big', team.id, undefined), 'insertPerson')
            let singleError: any
            try {
                await singleWriteRepository.createPerson(TEST_TIMESTAMP, { name: 'A' }, {}, {}, team.id, null, false, TEST_UUIDS.single, [{ distinctId: 'single-a', version: 0 }])
            } catch (e) {
                singleError = e
            }
            singleSpy.mockRestore()

            const dualSpy = mockDatabaseError(migrationPostgres, new PersonPropertiesSizeViolationError('too big', team.id, undefined), 'insertPerson')
            let dualError: any
            try {
                await dualWriteRepository.createPerson(TEST_TIMESTAMP, { name: 'A' }, {}, {}, team.id, null, false, TEST_UUIDS.dual, [{ distinctId: 'dual-a', version: 0 }])
            } catch (e) {
                dualError = e
            }
            dualSpy.mockRestore()

            expect(singleError).toEqual(dualError)

            // Database results are consistent
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.single],
                'verify-primary-create',
                'verify-secondary-create'
            )
        })

        it('createPerson() CreationConflict', async () => {
            const team = await getFirstTeam(postgres)
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
            const singleResult = await singleWriteRepository.createPerson(TEST_TIMESTAMP, { name: 'A' }, {}, {}, team.id, null, false, uuidFromDistinctId(team.id, distinctId), [{ distinctId, version: 0 }])
            const dualResult = await dualWriteRepository.createPerson(TEST_TIMESTAMP, { name: 'A' }, {}, {}, team.id, null, false, uuidFromDistinctId(team.id, distinctId), [{ distinctId, version: 0 }])

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

            await assertConsistentDatabaseErrorHandling(
                new Error('unhandled database error'),
                'insertPerson',
                () => singleWriteRepository.createPerson(TEST_TIMESTAMP, { name: 'A' }, {}, {}, team.id, null, false, TEST_UUIDS.single, [{ distinctId: 'single-a', version: 0 }]),
                () => dualWriteRepository.createPerson(TEST_TIMESTAMP, { name: 'A' }, {}, {}, team.id, null, false, TEST_UUIDS.single, [{ distinctId: 'dual-a', version: 0 }]),
                'unhandled database error'
            )
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.single],
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
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } = await createPersonsInBothRepos(team)

            const singleUpdateResult = await singleWriteRepository.updatePerson(singleCreatePersonResult.person, { properties: { name: 'B' } }, 'single-update')
            const dualUpdateResult = await dualWriteRepository.updatePerson(dualCreatePersonResult.person, { properties: { name: 'B' } }, 'dual-update')
            assertUpdatePersonContractParity(singleUpdateResult, dualUpdateResult)
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        it('updatePerson() unhandled database error', async() => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } = await createPersonsInBothRepos(team)

            // Test that both repositories handle database errors consistently
            await assertConsistentDatabaseErrorHandling(
                new Error('unhandled database error'),
                'updatePerson',
                () => singleWriteRepository.updatePerson(singleCreatePersonResult.person, { properties: { name: 'B' } }, 'single-update'),
                () => dualWriteRepository.updatePerson(dualCreatePersonResult.person, { properties: { name: 'B' } }, 'dual-update'),
                'unhandled database error'
            )

            // Verify that the database state remains consistent (no partial updates)
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        it('updatePerson() PersonPropertiesSizeViolation update attempts to violate the limit', async() => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } = await createPersonsInBothRepos(team)

            // NICKS TODO: we need to fix this, it should throw the check_properties_size constraint/code error
            // that the database throws when we try to update a person that is already oversized
            assertConsistentDatabaseErrorHandling(
                new PersonPropertiesSizeViolationError('PersonPropertiesSizeViolation', team.id, undefined),
                'updatePerson',
                () => singleWriteRepository.updatePerson(singleCreatePersonResult.person, { properties: { name: 'B' } }, 'single-update'),
                () => dualWriteRepository.updatePerson(dualCreatePersonResult.person, { properties: { name: 'B' } }, 'dual-update'),
                'PersonPropertiesSizeViolation'
            )

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        it('updatePerson() PersonPropertiesSizeViolation existing properties trimmed', async() => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } = await createPersonsInBothRepos(team)

            // we need custom database error mocking here, cause it's a special case

            // Force remediation branch by reporting the current record is already oversized
            const spySizeSingle = jest
                .spyOn((singleWriteRepository as any), 'personPropertiesSize')
                .mockResolvedValue(70000000)

            const spySizeDual = jest
                .spyOn((dualWriteRepository as any).primaryRepo, 'personPropertiesSize')
                .mockResolvedValue(70000000)
            
            const originalQueryPrimary = postgres.query.bind(postgres)
            let primaryUpdateCallCount = 0
            let sawRemediationTag = false
            const mockQueryPrimary = jest
                .spyOn(postgres, 'query')
                .mockImplementation(async (use, query, values, tag) => {
                    if (typeof query === 'string' && query.includes('UPDATE posthog_person SET')) {
                        primaryUpdateCallCount++
                        if (typeof tag === 'string' && tag.includes('oversized_properties_remediation')) {
                            sawRemediationTag = true
                            // allow remediation UPDATE to succeed
                            return originalQueryPrimary(use, query, values, tag)
                        }
                        // First UPDATE attempt fails with size violation
                        const error: any = new Error('Check constraint violation')
                        error.code = '23514'
                        error.constraint = 'check_properties_size'
                        throw error
                    }
                    return originalQueryPrimary(use, query, values, tag)
                })
            
            const updateToApply = {
                properties: {
                    $app_name: 'Application name with detailed information',
                    $app_version: 'Version 1.2.3 with build metadata',
                },
            }
            const singleUpdateResult = await singleWriteRepository.updatePerson(singleCreatePersonResult.person, updateToApply, 'single-update')
            const dualUpdateResult = await dualWriteRepository.updatePerson(dualCreatePersonResult.person, updateToApply, 'dual-update')

            // both single and primary called update twice
            expect(primaryUpdateCallCount).toBe(4)
            expect(sawRemediationTag).toBe(true)

            assertUpdatePersonContractParity(singleUpdateResult, dualUpdateResult)

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-update',
                'verify-secondary-update'
            )
            mockQueryPrimary.mockRestore()
            spySizeSingle.mockRestore()
            spySizeDual.mockRestore()
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
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } = await createPersonsInBothRepos(team)

            const singleDeleteResult = await singleWriteRepository.deletePerson(singleCreatePersonResult.person)
            const dualDeleteResult = await dualWriteRepository.deletePerson(dualCreatePersonResult.person)

            assertDeletePersonContractParity(singleDeleteResult, dualDeleteResult)

            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
        it('deletePerson() unhandled database error', async() => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } = await createPersonsInBothRepos(team)

            assertConsistentDatabaseErrorHandling(
                new Error('unhandled database error'),
                'deletePerson',
                () => singleWriteRepository.deletePerson(singleCreatePersonResult.person),
                () => dualWriteRepository.deletePerson(dualCreatePersonResult.person),
                'unhandled database error'
            )
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
        // NICKS TODO: implement this one
        // we just need to get the .code correct 
        it('deletePerson() deadlock detected', async() => {
            const team = await getFirstTeam(postgres)
            assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
    })
})

