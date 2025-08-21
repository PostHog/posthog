// for testing scenarios and ensuring that outcomes for dualwrite and singlewrite are the same
// we should test: 1. contract returned is the same, 2. consistency across primary and secondary
import { DateTime } from 'luxon'

import { TopicMessage } from '~/kafka/producer'
import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { InternalPerson } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'
import { UUIDT } from '~/utils/utils'

import { uuidFromDistinctId } from '../../person-uuid'
import { PersonPropertiesSizeViolationError } from './person-repository'
import { PostgresDualWritePersonRepository } from './postgres-dualwrite-person-repository'
import { PostgresPersonRepository } from './postgres-person-repository'
import {
    TEST_TIMESTAMP,
    TEST_UUIDS,
    assertConsistencyAcrossDatabases,
    assertConsistentDatabaseErrorHandling,
    assertCreatePersonConflictContractParity,
    assertCreatePersonContractParity,
    cleanupPrepared,
    getFirstTeam,
    mockDatabaseError,
    setupMigrationDb,
} from './test-helpers'

jest.mock('../../../../utils/logger')

describe('Postgres Single Write - Postgres Dual Write Compatibility', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let dualWriteRepository: PostgresDualWritePersonRepository
    let singleWriteRepository: PostgresPersonRepository

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
            singleWriteRepository.createPerson(createdAt, properties, {}, {}, team.id, null, false, singleUuid, [
                { distinctId: singleDistinctId, version: 0 },
            ]),
            dualWriteRepository.createPerson(createdAt, properties, {}, {}, team.id, null, false, dualUuid, [
                { distinctId: dualDistinctId, version: 0 },
            ]),
        ])

        if (!singleResult.success || !dualResult.success) {
            throw new Error('Failed to create test persons')
        }

        return {
            singleResult: { ...singleResult, person: singleResult.person },
            dualResult: { ...dualResult, person: dualResult.person },
        }
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        migrationPostgres = hub.db.postgresPersonMigration
        await setupMigrationDb(migrationPostgres)

        dualWriteRepository = new PostgresDualWritePersonRepository(postgres, migrationPostgres)
        singleWriteRepository = new PostgresPersonRepository(postgres)

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

            await assertConsistencyAcrossDatabases(
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

            const singleSpy = mockDatabaseError(
                postgres,
                new PersonPropertiesSizeViolationError('too big', team.id, undefined),
                'insertPerson'
            )
            let singleError: any
            try {
                await singleWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    TEST_UUIDS.single,
                    [{ distinctId: 'single-a', version: 0 }]
                )
            } catch (e) {
                singleError = e
            }
            singleSpy.mockRestore()

            const dualSpy = mockDatabaseError(
                migrationPostgres,
                new PersonPropertiesSizeViolationError('too big', team.id, undefined),
                'insertPerson'
            )
            let dualError: any
            try {
                await dualWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    TEST_UUIDS.dual,
                    [{ distinctId: 'dual-a', version: 0 }]
                )
            } catch (e) {
                dualError = e
            }
            dualSpy.mockRestore()

            expect(singleError).toEqual(dualError)

            await assertConsistencyAcrossDatabases(
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

            const singleResult = await singleWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'A' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, distinctId),
                [{ distinctId, version: 0 }]
            )
            const dualResult = await dualWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'A' },
                {},
                {},
                team.id,
                null,
                false,
                uuidFromDistinctId(team.id, distinctId),
                [{ distinctId, version: 0 }]
            )

            assertCreatePersonConflictContractParity(singleResult, dualResult)

            await assertConsistencyAcrossDatabases(
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
                postgres,
                new Error('unhandled database error'),
                'insertPerson',
                () =>
                    singleWriteRepository.createPerson(
                        TEST_TIMESTAMP,
                        { name: 'A' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        TEST_UUIDS.single,
                        [{ distinctId: 'single-a', version: 0 }]
                    ),
                () =>
                    dualWriteRepository.createPerson(
                        TEST_TIMESTAMP,
                        { name: 'A' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        TEST_UUIDS.single,
                        [{ distinctId: 'dual-a', version: 0 }]
                    ),
                'unhandled database error'
            )
            await assertConsistencyAcrossDatabases(
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
        function assertUpdatePersonContractParity(
            singleResult: [InternalPerson, TopicMessage[], boolean],
            dualResult: [InternalPerson, TopicMessage[], boolean]
        ) {
            expect(singleResult[0].properties).toEqual(dualResult[0].properties)
            // make sure message exists and has same topic
            expect(singleResult[1][0]?.topic).toEqual(dualResult[1][0]?.topic)
            expect(singleResult[2]).toEqual(dualResult[2])
        }
        it('happy path updatePerson()', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            const singleUpdateResult = await singleWriteRepository.updatePerson(
                singleCreatePersonResult.person,
                { properties: { name: 'B' } },
                'single-update'
            )
            const dualUpdateResult = await dualWriteRepository.updatePerson(
                dualCreatePersonResult.person,
                { properties: { name: 'B' } },
                'dual-update'
            )
            assertUpdatePersonContractParity(singleUpdateResult, dualUpdateResult)
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        it('updatePerson() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            await assertConsistentDatabaseErrorHandling(
                postgres,
                new Error('unhandled database error'),
                'updatePerson',
                () =>
                    singleWriteRepository.updatePerson(
                        singleCreatePersonResult.person,
                        { properties: { name: 'B' } },
                        'single-update'
                    ),
                () =>
                    dualWriteRepository.updatePerson(
                        dualCreatePersonResult.person,
                        { properties: { name: 'B' } },
                        'dual-update'
                    ),
                'unhandled database error'
            )

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        it('updatePerson() PersonPropertiesSizeViolation update attempts to violate the limit', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            await assertConsistentDatabaseErrorHandling(
                postgres,
                { message: 'Check constraint violation', code: '23514', constraint: 'check_properties_size' },
                'updatePerson',
                () =>
                    singleWriteRepository.updatePerson(
                        singleCreatePersonResult.person,
                        { properties: { name: 'B' } },
                        'single-update'
                    ),
                () =>
                    dualWriteRepository.updatePerson(
                        dualCreatePersonResult.person,
                        { properties: { name: 'B' } },
                        'dual-update'
                    ),
                PersonPropertiesSizeViolationError as any
            )

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-update',
                'verify-secondary-update'
            )
        })
        it('updatePerson() PersonPropertiesSizeViolation existing properties trimmed', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            const spySizeSingle = jest
                .spyOn(singleWriteRepository as any, 'personPropertiesSize')
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
                            return originalQueryPrimary(use, query, values, tag)
                        }
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
            const singleUpdateResult = await singleWriteRepository.updatePerson(
                singleCreatePersonResult.person,
                updateToApply,
                'single-update'
            )
            const dualUpdateResult = await dualWriteRepository.updatePerson(
                dualCreatePersonResult.person,
                updateToApply,
                'dual-update'
            )

            expect(primaryUpdateCallCount).toBe(4)
            expect(sawRemediationTag).toBe(true)

            assertUpdatePersonContractParity(singleUpdateResult, dualUpdateResult)

            await assertConsistencyAcrossDatabases(
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
            expect(singleResult.length).toEqual(dualResult.length)
            expect(singleResult[0].topic).toEqual(dualResult[0].topic)
        }
        it('happy path deletePerson()', async () => {
            const team = await getFirstTeam(postgres)
            const [singleCreatePersonResult, dualCreatePersonResult] = await Promise.all([
                singleWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    TEST_UUIDS.single,
                    []
                ),
                dualWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    TEST_UUIDS.dual,
                    []
                ),
            ])

            if (!singleCreatePersonResult.success || !dualCreatePersonResult.success) {
                throw new Error('Failed to create test persons')
            }

            const singleDeleteResult = await singleWriteRepository.deletePerson(singleCreatePersonResult.person)
            const dualDeleteResult = await dualWriteRepository.deletePerson(dualCreatePersonResult.person)

            assertDeletePersonContractParity(singleDeleteResult, dualDeleteResult)

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
        it('deletePerson() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)
            const [singleCreatePersonResult, dualCreatePersonResult] = await Promise.all([
                singleWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    '33333333-3333-3333-3333-333333333333',
                    []
                ),
                dualWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    '44444444-4444-4444-4444-444444444444',
                    []
                ),
            ])

            if (!singleCreatePersonResult.success || !dualCreatePersonResult.success) {
                throw new Error('Failed to create test persons')
            }

            await assertConsistentDatabaseErrorHandling(
                postgres,
                new Error('unhandled database error'),
                'deletePerson',
                () => singleWriteRepository.deletePerson(singleCreatePersonResult.person),
                () => dualWriteRepository.deletePerson(dualCreatePersonResult.person),
                'unhandled database error'
            )
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [TEST_UUIDS.dual],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
        it('deletePerson() deadlock detected', async () => {
            const team = await getFirstTeam(postgres)
            const [singleCreatePersonResult, dualCreatePersonResult] = await Promise.all([
                singleWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    '55555555-5555-5555-5555-555555555555',
                    []
                ),
                dualWriteRepository.createPerson(
                    TEST_TIMESTAMP,
                    { name: 'A' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    '66666666-6666-6666-6666-666666666666',
                    []
                ),
            ])

            if (!singleCreatePersonResult.success || !dualCreatePersonResult.success) {
                throw new Error('Failed to create test persons')
            }

            await assertConsistentDatabaseErrorHandling(
                postgres,
                { message: 'deadlock detected', code: '40P01' },
                'deletePerson',
                () => singleWriteRepository.deletePerson(singleCreatePersonResult.person),
                () => dualWriteRepository.deletePerson(dualCreatePersonResult.person),
                'deadlock detected'
            )

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                ['66666666-6666-6666-6666-666666666666'],
                'verify-primary-delete',
                'verify-secondary-delete'
            )
        })
    })

    describe('fetchPerson() is compatible between single and dual write', () => {
        function assertFetchPersonContractParity(
            singleResult: InternalPerson | undefined,
            dualResult: InternalPerson | undefined
        ) {
            if (singleResult === undefined) {
                expect(dualResult).toBeUndefined()
            } else if (dualResult === undefined) {
                expect(singleResult).toBeUndefined()
            } else {
                expect(singleResult.properties).toEqual(dualResult.properties)
                expect(singleResult.team_id).toEqual(dualResult.team_id)
                expect(singleResult.is_identified).toEqual(dualResult.is_identified)
            }
        }

        it('happy path fetchPerson()', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: _singleCreatePersonResult, dualResult: _dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            const singleFetchResult = await singleWriteRepository.fetchPerson(team.id, 'single-a')
            const dualFetchResult = await dualWriteRepository.fetchPerson(team.id, 'dual-a')

            assertFetchPersonContractParity(singleFetchResult, dualFetchResult)
        })

        it('fetchPerson() returns undefined for non-existent person', async () => {
            const team = await getFirstTeam(postgres)

            const singleFetchResult = await singleWriteRepository.fetchPerson(team.id, 'non-existent')
            const dualFetchResult = await dualWriteRepository.fetchPerson(team.id, 'non-existent')

            assertFetchPersonContractParity(singleFetchResult, dualFetchResult)
            expect(singleFetchResult).toBeUndefined()
            expect(dualFetchResult).toBeUndefined()
        })

        it('fetchPerson() with forUpdate lock', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: _singleCreatePersonResult, dualResult: _dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            const singleFetchResult = await singleWriteRepository.fetchPerson(team.id, 'single-a', { forUpdate: true })
            const dualFetchResult = await dualWriteRepository.fetchPerson(team.id, 'dual-a', { forUpdate: true })

            assertFetchPersonContractParity(singleFetchResult, dualFetchResult)
        })

        it('fetchPerson() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)
            await createPersonsInBothRepos(team)

            await assertConsistentDatabaseErrorHandling(
                postgres,
                new Error('unhandled database error'),
                'fetchPerson',
                () => singleWriteRepository.fetchPerson(team.id, 'single-a'),
                () => dualWriteRepository.fetchPerson(team.id, 'dual-a'),
                'unhandled database error'
            )
        })
    })

    describe('addDistinctId() is compatible between single and dual write and consistent between primary and secondary', () => {
        function assertAddDistinctIdContractParity(singleResult: TopicMessage[], dualResult: TopicMessage[]) {
            expect(singleResult.length).toEqual(dualResult.length)
            if (singleResult.length > 0) {
                expect(singleResult[0].topic).toEqual(dualResult[0].topic)
            }
        }

        it('happy path addDistinctId()', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            const singleAddResult = await singleWriteRepository.addDistinctId(
                singleCreatePersonResult.person,
                'single-b',
                1
            )
            const dualAddResult = await dualWriteRepository.addDistinctId(dualCreatePersonResult.person, 'dual-b', 1)

            assertAddDistinctIdContractParity(singleAddResult, dualAddResult)

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = (SELECT id FROM posthog_person WHERE uuid = $1)',
                [TEST_UUIDS.dual],
                'verify-primary-add-distinct-id',
                'verify-secondary-add-distinct-id'
            )
        })

        it('addDistinctId() duplicate distinct id conflict', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            let singleError: any
            try {
                await singleWriteRepository.addDistinctId(singleCreatePersonResult.person, 'single-a', 1)
            } catch (e) {
                singleError = e
            }

            let dualError: any
            try {
                await dualWriteRepository.addDistinctId(dualCreatePersonResult.person, 'dual-a', 1)
            } catch (e) {
                dualError = e
            }

            expect(singleError).toBeDefined()
            expect(dualError).toBeDefined()
            expect(singleError.message).toContain('unique')
            expect(dualError.message).toContain('unique')
        })

        it('addDistinctId() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            await assertConsistentDatabaseErrorHandling(
                postgres,
                new Error('unhandled database error'),
                'addDistinctId',
                () => singleWriteRepository.addDistinctId(singleCreatePersonResult.person, 'single-c', 1),
                () => dualWriteRepository.addDistinctId(dualCreatePersonResult.person, 'dual-c', 1),
                'unhandled database error'
            )
        })
    })

    describe('moveDistinctIds() is compatible between single and dual write and consistent between primary and secondary', () => {
        function assertMoveDistinctIdsContractParity(
            singleResult: { success: boolean; messages?: TopicMessage[]; distinctIdsMoved?: string[]; error?: string },
            dualResult: { success: boolean; messages?: TopicMessage[]; distinctIdsMoved?: string[]; error?: string }
        ) {
            expect(singleResult.success).toEqual(dualResult.success)
            if (singleResult.success) {
                expect(singleResult.messages?.length).toEqual(dualResult.messages?.length)
                expect(singleResult.distinctIdsMoved?.length).toEqual(dualResult.distinctIdsMoved?.length)
            } else {
                // When there's an error, check the error matches
                expect(singleResult.error).toEqual(dualResult.error)
            }
        }

        it('happy path moveDistinctIds()', async () => {
            const team = await getFirstTeam(postgres)

            // Create source persons with distinct IDs to move
            const sourceSingleResult = await singleWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Source' },
                {},
                {},
                team.id,
                null,
                false,
                '33333333-3333-3333-3333-333333333333',
                [{ distinctId: 'single-source', version: 0 }]
            )
            const sourceDualResult = await dualWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Source' },
                {},
                {},
                team.id,
                null,
                false,
                '44444444-4444-4444-4444-444444444444',
                [{ distinctId: 'dual-source', version: 0 }]
            )

            // Create target persons
            const targetSingleResult = await singleWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Target' },
                {},
                {},
                team.id,
                null,
                false,
                '55555555-5555-5555-5555-555555555555',
                [{ distinctId: 'single-target', version: 0 }]
            )
            const targetDualResult = await dualWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Target' },
                {},
                {},
                team.id,
                null,
                false,
                '66666666-6666-6666-6666-666666666666',
                [{ distinctId: 'dual-target', version: 0 }]
            )

            // Ensure all persons were created successfully
            if (
                !sourceSingleResult.success ||
                !targetSingleResult.success ||
                !sourceDualResult.success ||
                !targetDualResult.success
            ) {
                throw new Error('Failed to create test persons')
            }

            const singleMoveResult = await singleWriteRepository.moveDistinctIds(
                sourceSingleResult.person,
                targetSingleResult.person
            )
            const dualMoveResult = await dualWriteRepository.moveDistinctIds(
                sourceDualResult.person,
                targetDualResult.person
            )

            assertMoveDistinctIdsContractParity(singleMoveResult, dualMoveResult)

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = (SELECT id FROM posthog_person WHERE uuid = $1)',
                ['66666666-6666-6666-6666-666666666666'],
                'verify-primary-move-distinct-ids',
                'verify-secondary-move-distinct-ids'
            )
        })

        it('moveDistinctIds() foreign key constraint error when target deleted', async () => {
            const team = await getFirstTeam(postgres)

            // Create source persons
            const sourceSingleResult = await singleWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Source' },
                {},
                {},
                team.id,
                null,
                false,
                '77777777-7777-7777-7777-777777777777',
                [{ distinctId: 'single-source-fk', version: 0 }]
            )
            const sourceDualResult = await dualWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Source' },
                {},
                {},
                team.id,
                null,
                false,
                '88888888-8888-8888-8888-888888888888',
                [{ distinctId: 'dual-source-fk', version: 0 }]
            )

            // Ensure all persons were created successfully
            if (!sourceSingleResult.success || !sourceDualResult.success) {
                throw new Error('Failed to create test persons')
            }

            // Create mock target persons (will simulate them being deleted)
            const targetSingle = {
                ...sourceSingleResult.person,
                id: '999999',
                uuid: '99999999-9999-9999-9999-999999999999',
            }
            const targetDual = {
                ...sourceDualResult.person,
                id: '999998',
                uuid: '99999999-9999-9999-9999-999999999998',
            }

            // moveDistinctIds catches foreign key errors and returns { success: false, error: 'TargetNotFound' }
            // So we test that both repositories handle this case the same way
            const singleMockQuery = mockDatabaseError(
                postgres,
                { message: 'insert or update on table "posthog_persondistinctid" violates foreign key constraint' },
                'updateDistinctIdPerson'
            )
            const singleResult = await singleWriteRepository.moveDistinctIds(sourceSingleResult.person, targetSingle)
            singleMockQuery.mockRestore()

            // For dual-write, we need to mock both databases to fail to avoid prepared transaction issues
            const dualMockPrimary = mockDatabaseError(
                postgres,
                { message: 'insert or update on table "posthog_persondistinctid" violates foreign key constraint' },
                'updateDistinctIdPerson'
            )
            const dualMockSecondary = mockDatabaseError(
                migrationPostgres,
                { message: 'insert or update on table "posthog_persondistinctid" violates foreign key constraint' },
                'updateDistinctIdPerson'
            )
            const dualResult = await dualWriteRepository.moveDistinctIds(sourceDualResult.person, targetDual)
            dualMockPrimary.mockRestore()
            dualMockSecondary.mockRestore()

            // Both should return the same error result
            assertMoveDistinctIdsContractParity(singleResult, dualResult)
            expect(singleResult.success).toBe(false)
            expect(dualResult.success).toBe(false)
            expect((singleResult as any).error).toBe('TargetNotFound')
            expect((dualResult as any).error).toBe('TargetNotFound')
        })

        it('moveDistinctIds() with limit parameter', async () => {
            const team = await getFirstTeam(postgres)

            const sourceSingleResult = await singleWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Source with many IDs' },
                {},
                {},
                team.id,
                null,
                false,
                '77777777-7777-7777-7777-777777777777',
                [{ distinctId: 'single-source-limit', version: 0 }]
            )
            const sourceDualResult = await dualWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Source with many IDs' },
                {},
                {},
                team.id,
                null,
                false,
                '88888888-8888-8888-8888-888888888888',
                [{ distinctId: 'dual-source-limit', version: 0 }]
            )

            const targetSingleResult = await singleWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Target for limit test' },
                {},
                {},
                team.id,
                null,
                false,
                '99999999-9999-9999-9999-999999999999',
                [{ distinctId: 'single-target-limit', version: 0 }]
            )
            const targetDualResult = await dualWriteRepository.createPerson(
                TEST_TIMESTAMP,
                { name: 'Target for limit test' },
                {},
                {},
                team.id,
                null,
                false,
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                [{ distinctId: 'dual-target-limit', version: 0 }]
            )

            // Ensure all persons were created successfully
            if (
                !sourceSingleResult.success ||
                !targetSingleResult.success ||
                !sourceDualResult.success ||
                !targetDualResult.success
            ) {
                throw new Error('Failed to create test persons')
            }

            await singleWriteRepository.addDistinctId(sourceSingleResult.person, 'single-extra-1', 1)
            await singleWriteRepository.addDistinctId(sourceSingleResult.person, 'single-extra-2', 1)
            await singleWriteRepository.addDistinctId(sourceSingleResult.person, 'single-extra-3', 1)

            await dualWriteRepository.addDistinctId(sourceDualResult.person, 'dual-extra-1', 1)
            await dualWriteRepository.addDistinctId(sourceDualResult.person, 'dual-extra-2', 1)
            await dualWriteRepository.addDistinctId(sourceDualResult.person, 'dual-extra-3', 1)

            const singleMoveResult = await singleWriteRepository.moveDistinctIds(
                sourceSingleResult.person,
                targetSingleResult.person,
                2
            )
            const dualMoveResult = await dualWriteRepository.moveDistinctIds(
                sourceDualResult.person,
                targetDualResult.person,
                2
            )

            assertMoveDistinctIdsContractParity(singleMoveResult, dualMoveResult)

            expect(singleMoveResult.success).toBe(true)
            expect(dualMoveResult.success).toBe(true)

            if (singleMoveResult.success && dualMoveResult.success) {
                expect(singleMoveResult.distinctIdsMoved).toHaveLength(2)
                expect(dualMoveResult.distinctIdsMoved).toHaveLength(2)
                expect(singleMoveResult.messages).toHaveLength(2)
                expect(dualMoveResult.messages).toHaveLength(2)
            }

            const singleRemainingResult = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = (SELECT id FROM posthog_person WHERE uuid = $1)',
                ['77777777-7777-7777-7777-777777777777'],
                'countSingleRemaining'
            )
            expect(parseInt(singleRemainingResult.rows[0].count)).toBe(2)

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = (SELECT id FROM posthog_person WHERE uuid = $1)',
                ['88888888-8888-8888-8888-888888888888'],
                'verify-primary-source-remaining',
                'verify-secondary-source-remaining'
            )

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = (SELECT id FROM posthog_person WHERE uuid = $1)',
                ['aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'],
                'verify-primary-target-received',
                'verify-secondary-target-received'
            )
        })

        it('moveDistinctIds() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            await assertConsistentDatabaseErrorHandling(
                postgres,
                new Error('unhandled database error'),
                'updateDistinctIdPerson',
                () =>
                    singleWriteRepository.moveDistinctIds(
                        singleCreatePersonResult.person,
                        singleCreatePersonResult.person
                    ),
                () => dualWriteRepository.moveDistinctIds(dualCreatePersonResult.person, dualCreatePersonResult.person),
                'unhandled database error'
            )
        })
    })

    describe('addPersonlessDistinctId() is compatible between single and dual write and consistent between primary and secondary', () => {
        function assertAddPersonlessDistinctIdContractParity(singleResult: boolean, dualResult: boolean) {
            expect(singleResult).toEqual(dualResult)
        }

        it('happy path addPersonlessDistinctId()', async () => {
            const team = await getFirstTeam(postgres)

            const singleResult = await singleWriteRepository.addPersonlessDistinctId(team.id, 'single-personless')
            const dualResult = await dualWriteRepository.addPersonlessDistinctId(team.id, 'dual-personless')

            assertAddPersonlessDistinctIdContractParity(singleResult, dualResult)

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dual-personless'],
                'verify-primary-add-personless',
                'verify-secondary-add-personless'
            )
        })

        it('addPersonlessDistinctId() existing distinct id', async () => {
            const team = await getFirstTeam(postgres)

            // Add the same distinct ID twice
            await singleWriteRepository.addPersonlessDistinctId(team.id, 'single-personless-dup')
            await dualWriteRepository.addPersonlessDistinctId(team.id, 'dual-personless-dup')

            const singleResult = await singleWriteRepository.addPersonlessDistinctId(team.id, 'single-personless-dup')
            const dualResult = await dualWriteRepository.addPersonlessDistinctId(team.id, 'dual-personless-dup')

            assertAddPersonlessDistinctIdContractParity(singleResult, dualResult)
        })

        it('addPersonlessDistinctId() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)

            await assertConsistentDatabaseErrorHandling(
                postgres,
                new Error('unhandled database error'),
                'addPersonlessDistinctId',
                () => singleWriteRepository.addPersonlessDistinctId(team.id, 'single-error'),
                () => dualWriteRepository.addPersonlessDistinctId(team.id, 'dual-error'),
                'unhandled database error'
            )
        })
    })

    describe('addPersonlessDistinctIdForMerge() is compatible between single and dual write and consistent between primary and secondary', () => {
        function assertAddPersonlessDistinctIdForMergeContractParity(singleResult: boolean, dualResult: boolean) {
            expect(singleResult).toEqual(dualResult)
        }

        it('happy path addPersonlessDistinctIdForMerge()', async () => {
            const team = await getFirstTeam(postgres)

            const singleResult = await singleWriteRepository.addPersonlessDistinctIdForMerge(team.id, 'single-merge')
            const dualResult = await dualWriteRepository.addPersonlessDistinctIdForMerge(team.id, 'dual-merge')

            assertAddPersonlessDistinctIdForMergeContractParity(singleResult, dualResult)

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dual-merge'],
                'verify-primary-add-merge',
                'verify-secondary-add-merge'
            )
        })

        it('addPersonlessDistinctIdForMerge() updates existing non-merged', async () => {
            const team = await getFirstTeam(postgres)

            // First add as non-merged
            await singleWriteRepository.addPersonlessDistinctId(team.id, 'single-to-merge')
            await dualWriteRepository.addPersonlessDistinctId(team.id, 'dual-to-merge')

            // Then update to merged
            const singleResult = await singleWriteRepository.addPersonlessDistinctIdForMerge(team.id, 'single-to-merge')
            const dualResult = await dualWriteRepository.addPersonlessDistinctIdForMerge(team.id, 'dual-to-merge')

            assertAddPersonlessDistinctIdForMergeContractParity(singleResult, dualResult)
            expect(singleResult).toBe(false) // False because it was an update, not an insert
            expect(dualResult).toBe(false)

            // Verify is_merged is now true
            const singleCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'single-to-merge'],
                'check-single-merge'
            )
            const dualCheck = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dual-to-merge'],
                'check-dual-merge'
            )
            expect(singleCheck.rows[0].is_merged).toBe(true)
            expect(dualCheck.rows[0].is_merged).toBe(true)
        })

        it('addPersonlessDistinctIdForMerge() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)

            await assertConsistentDatabaseErrorHandling(
                postgres,
                new Error('unhandled database error'),
                'addPersonlessDistinctIdForMerge',
                () => singleWriteRepository.addPersonlessDistinctIdForMerge(team.id, 'single-merge-error'),
                () => dualWriteRepository.addPersonlessDistinctIdForMerge(team.id, 'dual-merge-error'),
                'unhandled database error'
            )
        })
    })

    describe('updateCohortsAndFeatureFlagsForMerge() is compatible between single and dual write and consistent between primary and secondary', () => {
        it('happy path updateCohortsAndFeatureFlagsForMerge()', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            // This method doesn't return anything, just verify it doesn't error
            await expect(
                singleWriteRepository.updateCohortsAndFeatureFlagsForMerge(
                    team.id,
                    singleCreatePersonResult.person.id,
                    singleCreatePersonResult.person.id
                )
            ).resolves.not.toThrow()

            await expect(
                dualWriteRepository.updateCohortsAndFeatureFlagsForMerge(
                    team.id,
                    dualCreatePersonResult.person.id,
                    dualCreatePersonResult.person.id
                )
            ).resolves.not.toThrow()

            // Verify consistency in cohort tables
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT COUNT(*) as count FROM posthog_cohortpeople',
                [],
                'verify-primary-cohort',
                'verify-secondary-cohort'
            )
        })

        it('updateCohortsAndFeatureFlagsForMerge() unhandled database error', async () => {
            const team = await getFirstTeam(postgres)
            const { singleResult: singleCreatePersonResult, dualResult: dualCreatePersonResult } =
                await createPersonsInBothRepos(team)

            // This method doesn't have special error handling, it just throws
            // We need to mock the specific query tag that this method uses: 'updateCohortAndFeatureFlagsPeople'
            const singleMockQuery = mockDatabaseError(
                postgres,
                new Error('unhandled database error'),
                'updateCohortAndFeatureFlagsPeople'
            )
            let singleError: any
            try {
                await singleWriteRepository.updateCohortsAndFeatureFlagsForMerge(
                    team.id,
                    singleCreatePersonResult.person.id,
                    singleCreatePersonResult.person.id
                )
            } catch (e) {
                singleError = e
            }
            singleMockQuery.mockRestore()

            const dualMockQuery = mockDatabaseError(
                postgres,
                new Error('unhandled database error'),
                'updateCohortAndFeatureFlagsPeople'
            )
            let dualError: any
            try {
                await dualWriteRepository.updateCohortsAndFeatureFlagsForMerge(
                    team.id,
                    dualCreatePersonResult.person.id,
                    dualCreatePersonResult.person.id
                )
            } catch (e) {
                dualError = e
            }
            dualMockQuery.mockRestore()

            // Both should throw the same error
            expect(singleError).toBeDefined()
            expect(dualError).toBeDefined()
            expect(singleError.message).toBe('unhandled database error')
            expect(dualError.message).toBe('unhandled database error')
        })
    })
})
