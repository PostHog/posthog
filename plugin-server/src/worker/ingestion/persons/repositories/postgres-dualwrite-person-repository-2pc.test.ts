import { DateTime } from 'luxon'

import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'

import { PostgresDualWritePersonRepository } from './postgres-dualwrite-person-repository'
import {
    assertConsistencyAcrossDatabases,
    cleanupPrepared,
    getFirstTeam,
    mockDatabaseError,
    setupMigrationDb,
} from './test-helpers'

jest.mock('../../../../utils/logger')

describe('PostgresDualWritePersonRepository 2PC Dual-Write Tests', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let repository: PostgresDualWritePersonRepository

    async function verifyDistinctIdsForPerson(
        teamId: number,
        personId: string,
        personUuid: string,
        expectedDids: string[]
    ) {
        await assertConsistencyAcrossDatabases(
            postgres,
            migrationPostgres,
            `SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id`,
            [personId],
            'verify-primary-dids',
            'verify-secondary-dids-placeholder'
        )

        // For secondary DB, we need to use UUID to find person ID
        const secondaryDids = await migrationPostgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
            [teamId, personUuid],
            'verify-secondary-dids'
        )

        const primaryDids = await postgres.query(
            PostgresUse.PERSONS_READ,
            'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
            [personId],
            'verify-primary-dids-final'
        )

        expect(primaryDids.rows.map((r: any) => r.distinct_id)).toEqual(expectedDids)
        expect(secondaryDids.rows.map((r: any) => r.distinct_id)).toEqual(expectedDids)
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        migrationPostgres = hub.db.postgresPersonMigration
        await setupMigrationDb(migrationPostgres)

        repository = new PostgresDualWritePersonRepository(postgres, migrationPostgres)

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)
    })

    afterEach(async () => {
        await cleanupPrepared(hub)
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('createPerson() 2PC tests', () => {
        it('writes to both primary and secondary (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'

            const result = await repository.createPerson(
                createdAt,
                { name: 'Dual Write' },
                {},
                {},
                team.id,
                null,
                true,
                uuid,
                [{ distinctId: 'dw-1', version: 0 }]
            )
            expect(result.success).toBe(true)

            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, uuid],
                'verify-primary-create'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, uuid],
                'verify-secondary-create'
            )
            expect(primary.rows.length).toBe(1)
            expect(secondary.rows.length).toBe(1)

            const pids = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dw-1'],
                'verify-primary-distinct'
            )
            const sids = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dw-1'],
                'verify-secondary-distinct'
            )
            expect(pids.rows.length).toBe(1)
            expect(sids.rows.length).toBe(1)
        })

        it('rolls back both when secondary write fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '88888888-8888-8888-8888-888888888888'
            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'createPerson')
                .mockRejectedValue(new Error('simulated secondary failure'))

            await expect(
                repository.createPerson(createdAt, { y: 1 }, {}, {}, team.id, null, false, uuid, [
                    { distinctId: 'dw-fail' },
                ])
            ).rejects.toThrow('simulated secondary failure')

            spy.mockRestore()

            const primaryPersons = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT id FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, uuid],
                'verify-primary-no-create-after-rollback'
            )
            const secondaryPersons = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT id FROM posthog_person WHERE team_id = $1 AND uuid = $2',
                [team.id, uuid],
                'verify-secondary-no-create-after-rollback'
            )
            expect(primaryPersons.rows.length).toBe(0)
            expect(secondaryPersons.rows.length).toBe(0)
        })

        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'

            const mockSpy = mockDatabaseError(postgres, new Error('primary database connection lost'), 'insertPerson')

            await expect(
                repository.createPerson(createdAt, { name: 'Test Person' }, {}, {}, team.id, null, false, uuid, [
                    { distinctId: 'test-primary-fail', version: 0 },
                ])
            ).rejects.toThrow('primary database connection lost')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-person-rollback',
                'verify-secondary-person-rollback'
            )

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['test-primary-fail'],
                'verify-primary-did-rollback',
                'verify-secondary-did-rollback'
            )

            const personCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-empty-person'
            )
            const didCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['test-primary-fail'],
                'verify-empty-did'
            )
            expect(personCheck.rows.length).toBe(0)
            expect(didCheck.rows.length).toBe(0)
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '22222222-2222-2222-2222-222222222222'

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary database connection lost'),
                'insertPerson'
            )

            await expect(
                repository.createPerson(createdAt, { name: 'Test Person' }, {}, {}, team.id, null, false, uuid, [
                    { distinctId: 'test-secondary-fail', version: 0 },
                ])
            ).rejects.toThrow('secondary database connection lost')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-person-rollback',
                'verify-secondary-person-rollback'
            )

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['test-secondary-fail'],
                'verify-primary-did-rollback',
                'verify-secondary-did-rollback'
            )

            const personCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-empty-person'
            )
            const didCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['test-secondary-fail'],
                'verify-empty-did'
            )
            expect(personCheck.rows.length).toBe(0)
            expect(didCheck.rows.length).toBe(0)
        })
    })

    describe('updatePerson() 2PC tests', () => {
        it('replicates to secondary (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '22222222-2222-2222-2222-222222222222'
            const { person } = (await repository.createPerson(
                createdAt,
                { name: 'A' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'dw-2' }]
            )) as any

            const [updated] = await repository.updatePerson(person, { properties: { name: 'B' } })

            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE id = $1',
                [updated.id],
                'verify-primary-update'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-update'
            )
            expect(primary.rows[0].properties).toEqual({ name: 'B' })
            expect(secondary.rows[0].properties).toEqual({ name: 'B' })
        })

        it('rolls back both when secondary update fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '88888888-8888-8888-8888-888888888888'
            const { person } = (await repository.createPerson(createdAt, { y: 1 }, {}, {}, team.id, null, false, uuid, [
                { distinctId: 'dw-fail' },
            ])) as any

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'updatePerson')
                .mockRejectedValue(new Error('simulated secondary failure'))

            await expect(repository.updatePerson(person, { properties: { y: 2 } }, 'test-fail')).rejects.toThrow(
                'simulated secondary failure'
            )

            spy.mockRestore()

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-rolled-back'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-rolled-back'
            )
            expect(p.rows[0].properties).toEqual({ y: 1 })
            expect(s.rows[0].properties).toEqual({ y: 1 })
        })

        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '33333333-3333-3333-3333-333333333333'

            const { person } = (await repository.createPerson(
                createdAt,
                { name: 'Original' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'update-primary-fail', version: 0 }]
            )) as any

            const mockSpy = mockDatabaseError(postgres, new Error('primary update failed'), 'updatePerson')

            await expect(repository.updatePerson(person, { properties: { name: 'Updated' } })).rejects.toThrow(
                'primary update failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-unchanged',
                'verify-secondary-unchanged'
            )

            const personCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-properties'
            )
            expect(personCheck.rows[0].properties).toEqual({ name: 'Original' })
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '44444444-4444-4444-4444-444444444444'

            const { person } = (await repository.createPerson(
                createdAt,
                { name: 'Original' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'update-secondary-fail', version: 0 }]
            )) as any

            const mockSpy = mockDatabaseError(migrationPostgres, new Error('secondary update failed'), 'updatePerson')

            await expect(repository.updatePerson(person, { properties: { name: 'Updated' } })).rejects.toThrow(
                'secondary update failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-unchanged',
                'verify-secondary-unchanged'
            )

            const personCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-properties'
            )
            expect(personCheck.rows[0].properties).toEqual({ name: 'Original' })
        })
    })

    describe('deletePerson() 2PC tests', () => {
        it('removes from both (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '33333333-3333-3333-3333-333333333333'
            const { person } = (await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, uuid)) as any

            await repository.deletePerson(person)

            const primary = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-delete'
            )
            const secondary = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-delete'
            )
            expect(primary.rows.length).toBe(0)
            expect(secondary.rows.length).toBe(0)
        })

        it('rolls back both when secondary delete fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-16T10:30:00.000Z').toUTC()
            const uuid = '33333333-3333-3333-3333-333333333334'
            const { person } = (await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, uuid)) as any

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'deletePerson')
                .mockRejectedValue(new Error('simulated secondary delete failure'))

            await expect(repository.deletePerson(person)).rejects.toThrow('simulated secondary delete failure')

            spy.mockRestore()

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-delete-rolled-back'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-delete-rolled-back'
            )
            expect(p.rows.length).toBe(1)
            expect(s.rows.length).toBe(1)
        })

        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '55555555-5555-5555-5555-555555555555'

            const { person } = (await repository.createPerson(
                createdAt,
                { name: 'To Delete' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'delete-primary-fail', version: 0 }]
            )) as any

            const mockSpy = mockDatabaseError(postgres, new Error('primary delete failed'), 'deletePerson')

            await expect(repository.deletePerson(person)).rejects.toThrow('primary delete failed')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-exists',
                'verify-secondary-exists'
            )

            const personCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-person-exists'
            )
            expect(personCheck.rows.length).toBe(1)
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '66666666-6666-6666-6666-666666666666'

            const { person } = (await repository.createPerson(
                createdAt,
                { name: 'To Delete' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'delete-secondary-fail', version: 0 }]
            )) as any

            const mockSpy = mockDatabaseError(migrationPostgres, new Error('secondary delete failed'), 'deletePerson')

            await expect(repository.deletePerson(person)).rejects.toThrow('secondary delete failed')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-exists',
                'verify-secondary-exists'
            )

            const personCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-person-exists'
            )
            expect(personCheck.rows.length).toBe(1)
        })
    })

    describe('addDistinctId() 2PC tests', () => {
        it('writes to both (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '44444444-4444-4444-4444-444444444444'
            const { person } = (await repository.createPerson(createdAt, {}, {}, {}, team.id, null, true, uuid, [
                { distinctId: 'dw-3' },
            ])) as any

            await repository.addDistinctId(person, 'dw-3b', 1)

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dw-3b'],
                'verify-primary-add-distinct'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dw-3b'],
                'verify-secondary-add-distinct'
            )
            expect(p.rows.length).toBe(1)
            expect(s.rows.length).toBe(1)
        })

        it('rolls back both when secondary addDistinctId fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-17T10:30:00.000Z').toUTC()
            const uuid = '44444444-4444-4444-4444-444444444445'
            const { person } = (await repository.createPerson(createdAt, {}, {}, {}, team.id, null, true, uuid, [
                { distinctId: 'dw-3c', version: 0 },
            ])) as any

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'addDistinctId')
                .mockRejectedValue(new Error('simulated secondary addDistinctId failure'))

            await expect(repository.addDistinctId(person, 'dw-3d', 1)).rejects.toThrow(
                'simulated secondary addDistinctId failure'
            )

            spy.mockRestore()

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dw-3d'],
                'verify-primary-add-distinct-rolled-back'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, 'dw-3d'],
                'verify-secondary-add-distinct-rolled-back'
            )
            expect(p.rows.length).toBe(0)
            expect(s.rows.length).toBe(0)
        })

        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '77777777-7777-7777-7777-777777777777'

            const { person } = (await repository.createPerson(
                createdAt,
                { name: 'Test' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'original-did', version: 0 }]
            )) as any

            const mockSpy = mockDatabaseError(postgres, new Error('primary addDistinctId failed'), 'addDistinctId')

            await expect(repository.addDistinctId(person, 'new-did-primary-fail', 1)).rejects.toThrow(
                'primary addDistinctId failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['new-did-primary-fail'],
                'verify-primary-no-new-did',
                'verify-secondary-no-new-did'
            )

            const didCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['new-did-primary-fail'],
                'verify-no-did'
            )
            expect(didCheck.rows.length).toBe(0)
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '88888888-8888-8888-8888-888888888888'

            const { person } = (await repository.createPerson(
                createdAt,
                { name: 'Test' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'original-did-2', version: 0 }]
            )) as any

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary addDistinctId failed'),
                'addDistinctId'
            )

            await expect(repository.addDistinctId(person, 'new-did-secondary-fail', 1)).rejects.toThrow(
                'secondary addDistinctId failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['new-did-secondary-fail'],
                'verify-primary-no-new-did',
                'verify-secondary-no-new-did'
            )

            const didCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['new-did-secondary-fail'],
                'verify-no-did'
            )
            expect(didCheck.rows.length).toBe(0)
        })
    })

    describe('moveDistinctIds() 2PC tests', () => {
        it('affects both sides (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const srcUuid = '55555555-5555-5555-5555-555555555555'
            const tgtUuid = '66666666-6666-6666-6666-666666666666'

            const { person: src } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                srcUuid,
                [{ distinctId: 'src-a', version: 0 }]
            )) as any
            const { person: tgt } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                tgtUuid,
                [{ distinctId: 'tgt-a', version: 0 }]
            )) as any

            await repository.addDistinctId(src, 'src-b', 1)

            const res = await repository.moveDistinctIds(src, tgt)
            expect(res.success).toBe(true)

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                [tgt.id],
                'verify-primary-move'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2)',
                [team.id, tgtUuid],
                'verify-secondary-move'
            )
            const pIds = p.rows.map((r: any) => r.distinct_id).sort()
            const sIds = s.rows.map((r: any) => r.distinct_id).sort()
            expect(pIds).toEqual(expect.arrayContaining(['src-a', 'src-b', 'tgt-a']))
            expect(sIds).toEqual(expect.arrayContaining(['src-a', 'src-b', 'tgt-a']))
        })

        it('rolls back both when secondary moveDistinctIds fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-18T10:30:00.000Z').toUTC()
            const srcUuid = '55555555-5555-5555-5555-555555555556'
            const tgtUuid = '66666666-6666-6666-6666-666666666667'

            const { person: src } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                srcUuid,
                [{ distinctId: 'src-c', version: 0 }]
            )) as any
            const { person: tgt } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                tgtUuid,
                [{ distinctId: 'tgt-c', version: 0 }]
            )) as any

            await repository.addDistinctId(src, 'src-d', 1)

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'moveDistinctIds')
                .mockRejectedValue(new Error('simulated secondary moveDistinctIds failure'))

            await expect(repository.moveDistinctIds(src, tgt)).rejects.toThrow(
                'simulated secondary moveDistinctIds failure'
            )

            spy.mockRestore()

            const pSrc = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                [src.id],
                'verify-primary-move-rolled-back-src'
            )
            expect(pSrc.rows.map((r: any) => r.distinct_id).sort()).toEqual(['src-c', 'src-d'])
            const pTgt = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 ORDER BY distinct_id',
                [tgt.id],
                'verify-primary-move-rolled-back-tgt'
            )
            expect(pTgt.rows.map((r: any) => r.distinct_id).sort()).toEqual(['tgt-c'])
            const sTgt = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT distinct_id FROM posthog_persondistinctid WHERE team_id = $1 AND person_id = (SELECT id FROM posthog_person WHERE uuid = $2) ORDER BY distinct_id',
                [team.id, tgtUuid],
                'verify-secondary-move-rolled-back-tgt'
            )
            expect(sTgt.rows.map((r: any) => r.distinct_id).sort()).toEqual(['tgt-c'])
        })

        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const srcUuid = '99999999-9999-9999-9999-999999999999'
            const tgtUuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

            const { person: src } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                srcUuid,
                [{ distinctId: 'src-did', version: 0 }]
            )) as any

            const { person: tgt } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                tgtUuid,
                [{ distinctId: 'tgt-did', version: 0 }]
            )) as any

            await repository.addDistinctId(src, 'src-did-2', 1)

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary moveDistinctIds failed'),
                'updateDistinctIdPerson'
            )

            await expect(repository.moveDistinctIds(src, tgt)).rejects.toThrow('primary moveDistinctIds failed')

            mockSpy.mockRestore()

            await verifyDistinctIdsForPerson(team.id, src.id, srcUuid, ['src-did', 'src-did-2'])
            await verifyDistinctIdsForPerson(team.id, tgt.id, tgtUuid, ['tgt-did'])
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const srcUuid = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
            const tgtUuid = 'cccccccc-cccc-cccc-cccc-cccccccccccc'

            const { person: src } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                srcUuid,
                [{ distinctId: 'src-did-b', version: 0 }]
            )) as any

            const { person: tgt } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                tgtUuid,
                [{ distinctId: 'tgt-did-b', version: 0 }]
            )) as any

            await repository.addDistinctId(src, 'src-did-b-2', 1)

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary moveDistinctIds failed'),
                'updateDistinctIdPerson'
            )

            await expect(repository.moveDistinctIds(src, tgt)).rejects.toThrow('secondary moveDistinctIds failed')

            mockSpy.mockRestore()

            await verifyDistinctIdsForPerson(team.id, src.id, srcUuid, ['src-did-b', 'src-did-b-2'])
            await verifyDistinctIdsForPerson(team.id, tgt.id, tgtUuid, ['tgt-did-b'])
        })
    })

    describe('addPersonlessDistinctId() 2PC tests', () => {
        it('writes to both (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-1'
            const inserted = await repository.addPersonlessDistinctId(team.id, did)
            expect(inserted === true || inserted === false).toBe(true)

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-personless'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-secondary-personless'
            )
            expect(p.rows.length).toBe(1)
            expect(s.rows.length).toBe(1)
        })

        it('rolls back both when secondary addPersonlessDistinctId fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-fail'

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'addPersonlessDistinctId')
                .mockRejectedValue(new Error('simulated secondary personless failure'))

            await expect(repository.addPersonlessDistinctId(team.id, did)).rejects.toThrow(
                'simulated secondary personless failure'
            )

            spy.mockRestore()

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-personless-rolled-back'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-secondary-personless-rolled-back'
            )
            expect(p.rows.length).toBe(0)
            expect(s.rows.length).toBe(0)
        })

        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-primary-fail'

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary addPersonlessDistinctId failed'),
                'addPersonlessDistinctId'
            )

            await expect(repository.addPersonlessDistinctId(team.id, did)).rejects.toThrow(
                'primary addPersonlessDistinctId failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-personless',
                'verify-secondary-no-personless'
            )

            const recordCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-no-personless'
            )
            expect(recordCheck.rows.length).toBe(0)
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-secondary-fail'

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary addPersonlessDistinctId failed'),
                'addPersonlessDistinctId'
            )

            await expect(repository.addPersonlessDistinctId(team.id, did)).rejects.toThrow(
                'secondary addPersonlessDistinctId failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-personless',
                'verify-secondary-no-personless'
            )

            const recordCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-no-personless'
            )
            expect(recordCheck.rows.length).toBe(0)
        })
    })

    describe('addPersonlessDistinctIdForMerge() 2PC tests', () => {
        it('writes to both (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-merge-1'
            const merged = await repository.addPersonlessDistinctIdForMerge(team.id, did)
            expect(merged === true || merged === false).toBe(true)

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-personless-merge'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-secondary-personless-merge'
            )
            expect(p.rows.length).toBe(1)
            expect(s.rows.length).toBe(1)
        })

        it('rolls back both when secondary addPersonlessDistinctIdForMerge fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-merge-2'

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'addPersonlessDistinctIdForMerge')
                .mockRejectedValue(new Error('simulated secondary personless-merge failure'))

            await expect(repository.addPersonlessDistinctIdForMerge(team.id, did)).rejects.toThrow(
                'simulated secondary personless-merge failure'
            )

            spy.mockRestore()

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-personless-merge-rolled-back'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-secondary-personless-merge-rolled-back'
            )
            expect(p.rows.length).toBe(0)
            expect(s.rows.length).toBe(0)
        })

        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-merge-primary-fail'

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary addPersonlessDistinctIdForMerge failed'),
                'addPersonlessDistinctIdForMerge'
            )

            await expect(repository.addPersonlessDistinctIdForMerge(team.id, did)).rejects.toThrow(
                'primary addPersonlessDistinctIdForMerge failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-merge',
                'verify-secondary-no-merge'
            )

            const recordCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-no-merge'
            )
            expect(recordCheck.rows.length).toBe(0)
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-merge-secondary-fail'

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary addPersonlessDistinctIdForMerge failed'),
                'addPersonlessDistinctIdForMerge'
            )

            await expect(repository.addPersonlessDistinctIdForMerge(team.id, did)).rejects.toThrow(
                'secondary addPersonlessDistinctIdForMerge failed'
            )

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-merge',
                'verify-secondary-no-merge'
            )

            const recordCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-no-merge'
            )
            expect(recordCheck.rows.length).toBe(0)
        })
    })

    describe('updatePersonAssertVersion() non-2PC test', () => {
        it('updates secondary on primary success (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '77777777-7777-7777-7777-777777777777'
            const { person } = (await repository.createPerson(
                createdAt,
                { x: 1 },
                {},
                {},
                team.id,
                null,
                false,
                uuid
            )) as any

            const [version] = await repository.updatePersonAssertVersion({
                id: person.id,
                team_id: person.team_id,
                uuid: person.uuid,
                distinct_id: 'dw-assert',
                properties: { x: 2 },
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: person.created_at,
                version: person.version,
                is_identified: person.is_identified,
                is_user_id: person.is_user_id,
                needs_write: true,
                properties_to_set: { x: 2 },
                properties_to_unset: [],
                original_is_identified: false,
                original_created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z'),
            })
            expect(version).toBe(person.version + 1)

            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties, version FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-assert'
            )
            expect(s.rows[0].properties).toEqual({ x: 2 })
            expect(Number(s.rows[0].version || 0)).toBe(person.version + 1)
        })

        it('does not rollback primary when secondary fails (non-2PC)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-19T10:30:00.000Z').toUTC()
            const uuid = '77777777-7777-7777-7777-777777777778'
            const { person } = (await repository.createPerson(
                createdAt,
                { x: 1 },
                {},
                {},
                team.id,
                null,
                false,
                uuid
            )) as any

            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'updatePersonAssertVersion')
                .mockRejectedValue(new Error('secondary assert-version failure'))

            await expect(
                repository.updatePersonAssertVersion({
                    id: person.id,
                    team_id: person.team_id,
                    uuid: person.uuid,
                    distinct_id: 'dw-assert-2',
                    properties: { x: 2 },
                    properties_last_updated_at: {},
                    properties_last_operation: {},
                    created_at: person.created_at,
                    version: person.version,
                    is_identified: person.is_identified,
                    is_user_id: person.is_user_id,
                    needs_write: true,
                    properties_to_set: { x: 2 },
                    properties_to_unset: [],
                    original_is_identified: false,
                    original_created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z'),
                })
            ).rejects.toThrow('secondary assert-version failure')

            spy.mockRestore()

            const p = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-assert-non-tx'
            )
            const s = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-assert-non-tx'
            )
            expect(p.rows[0].properties).toEqual({ x: 2 })
            expect(s.rows[0].properties).toEqual({ x: 1 })
        })
    })

    describe('updateCohortsAndFeatureFlagsForMerge() non-2PC tests', () => {
        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid1 = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
            const uuid2 = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'

            // Create two persons
            const { person: person1 } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                uuid1,
                [{ distinctId: 'person1', version: 0 }]
            )) as any

            const { person: person2 } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                uuid2,
                [{ distinctId: 'person2', version: 0 }]
            )) as any

            // Mock primary database to fail during cohort update
            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary cohort update failed'),
                'updateCohortAndFeatureFlagsPeople'
            )

            await expect(
                repository.updateCohortsAndFeatureFlagsForMerge(team.id, person1.id, person2.id)
            ).rejects.toThrow('primary cohort update failed')

            mockSpy.mockRestore()

            // Since this method doesn't use 2PC (it's a best-effort update),
            // we just verify that the error was thrown correctly
            // The actual state depends on when the error occurred
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid1 = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
            const uuid2 = '00000000-0000-0000-0000-000000000001'

            // Create two persons
            const { person: person1 } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                uuid1,
                [{ distinctId: 'person1b', version: 0 }]
            )) as any

            const { person: person2 } = (await repository.createPerson(
                createdAt,
                {},
                {},
                {},
                team.id,
                null,
                false,
                uuid2,
                [{ distinctId: 'person2b', version: 0 }]
            )) as any

            // Mock secondary database to fail during cohort update
            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary cohort update failed'),
                'updateCohortAndFeatureFlagsPeople'
            )

            await expect(
                repository.updateCohortsAndFeatureFlagsForMerge(team.id, person1.id, person2.id)
            ).rejects.toThrow('secondary cohort update failed')

            mockSpy.mockRestore()

            // Since this method doesn't use 2PC (it's a best-effort update),
            // we just verify that the error was thrown correctly
        })
    })

    describe('inTransaction() 2PC tests', () => {
        it('should execute multiple operations atomically within a transaction (happy path)', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'

            const result = await repository.inTransaction('test-multi-operation', async (tx) => {
                // Create a person within the transaction
                const createResult = await tx.createPerson(
                    createdAt,
                    { name: 'Transaction Test', age: 25 },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuid,
                    [{ distinctId: 'tx-did-1', version: 0 }]
                )

                if (!createResult.success) {
                    throw new Error('Failed to create person in transaction')
                }

                // Add another distinct ID
                await tx.addDistinctId(createResult.person, 'tx-did-2', 1)

                // Update the person
                const [updatedPerson] = await tx.updatePerson(createResult.person, {
                    properties: { name: 'Updated Name', age: 26 },
                })

                return updatedPerson
            })

            // Verify the transaction succeeded and data is consistent across both databases
            const primaryPerson = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-tx-person'
            )
            const secondaryPerson = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT * FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-tx-person'
            )

            expect(primaryPerson.rows.length).toBe(1)
            expect(secondaryPerson.rows.length).toBe(1)
            expect(primaryPerson.rows[0].properties).toEqual({ name: 'Updated Name', age: 26 })
            expect(secondaryPerson.rows[0].properties).toEqual({ name: 'Updated Name', age: 26 })

            // Verify distinct IDs
            await verifyDistinctIdsForPerson(team.id, result.id, uuid, ['tx-did-1', 'tx-did-2'])
        })

        it('should rollback all operations when any operation fails within transaction', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const uuid = '22222222-2222-2222-2222-222222222222'

            // Mock to make addDistinctId fail on secondary
            const spy = jest.spyOn((repository as any).secondaryRepo, 'addDistinctId')
            spy.mockRejectedValueOnce(new Error('simulated addDistinctId failure in transaction'))

            await expect(
                repository.inTransaction('test-rollback', async (tx) => {
                    // Create a person - this should succeed initially
                    const createResult = await tx.createPerson(
                        createdAt,
                        { name: 'Will Rollback' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuid,
                        [{ distinctId: 'tx-rollback-1', version: 0 }]
                    )

                    if (!createResult.success) {
                        throw new Error('Failed to create person')
                    }

                    await tx.addDistinctId(createResult.person, 'tx-rollback-2', 1)

                    return createResult.person
                })
            ).rejects.toThrow('simulated addDistinctId failure in transaction')

            spy.mockRestore()

            // Verify nothing was persisted to either database
            const primaryCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-rollback'
            )
            const secondaryCheck = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-secondary-rollback'
            )

            expect(primaryCheck.rows.length).toBe(0)
            expect(secondaryCheck.rows.length).toBe(0)

            // Verify distinct IDs were also rolled back
            const primaryDids = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id IN ($1, $2)',
                ['tx-rollback-1', 'tx-rollback-2'],
                'verify-primary-dids-rollback'
            )
            const secondaryDids = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id IN ($1, $2)',
                ['tx-rollback-1', 'tx-rollback-2'],
                'verify-secondary-dids-rollback'
            )

            expect(primaryDids.rows.length).toBe(0)
            expect(secondaryDids.rows.length).toBe(0)
        })

        it('should handle complex merge scenario within transaction', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const sourceUuid = '33333333-3333-3333-3333-333333333333'
            const targetUuid = '44444444-4444-4444-4444-444444444444'

            // Create source and target persons first
            const { person: sourcePerson } = (await repository.createPerson(
                createdAt,
                { source: true },
                {},
                {},
                team.id,
                null,
                false,
                sourceUuid,
                [{ distinctId: 'source-main', version: 0 }]
            )) as any

            const { person: targetPerson } = (await repository.createPerson(
                createdAt,
                { target: true },
                {},
                {},
                team.id,
                null,
                false,
                targetUuid,
                [{ distinctId: 'target-main', version: 0 }]
            )) as any

            // Add extra distinct IDs to source
            await repository.addDistinctId(sourcePerson, 'source-extra-1', 1)
            await repository.addDistinctId(sourcePerson, 'source-extra-2', 2)

            // Perform merge operations in a transaction
            await repository.inTransaction('test-merge', async (tx) => {
                // Move distinct IDs from source to target
                const moveResult = await tx.moveDistinctIds(sourcePerson, targetPerson)
                if (!moveResult.success) {
                    throw new Error('Failed to move distinct IDs')
                }

                // Delete the source person
                await tx.deletePerson(sourcePerson)

                // Update cohorts and feature flags
                await tx.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePerson.id, targetPerson.id)

                return { moveResult, targetPersonId: targetPerson.id }
            })

            // Verify source person is deleted
            const sourceCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [sourceUuid],
                'verify-source-deleted'
            )
            expect(sourceCheck.rows.length).toBe(0)

            // Verify all distinct IDs moved to target
            await verifyDistinctIdsForPerson(team.id, targetPerson.id, targetUuid, [
                'source-extra-1',
                'source-extra-2',
                'source-main',
                'target-main',
            ])
        })

        it('should rollback merge operations when moveDistinctIds fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const sourceUuid = '55555555-5555-5555-5555-555555555555'
            const targetUuid = '66666666-6666-6666-6666-666666666666'

            // Create source and target persons
            const { person: sourcePerson } = (await repository.createPerson(
                createdAt,
                { source: true },
                {},
                {},
                team.id,
                null,
                false,
                sourceUuid,
                [{ distinctId: 'merge-fail-source', version: 0 }]
            )) as any

            const { person: targetPerson } = (await repository.createPerson(
                createdAt,
                { target: true },
                {},
                {},
                team.id,
                null,
                false,
                targetUuid,
                [{ distinctId: 'merge-fail-target', version: 0 }]
            )) as any

            // Mock moveDistinctIds to fail
            const spy = jest.spyOn((repository as any).secondaryRepo, 'moveDistinctIds')
            spy.mockRejectedValueOnce(new Error('simulated moveDistinctIds failure'))

            await expect(
                repository.inTransaction('test-merge-rollback', async (tx) => {
                    // This should fail and rollback
                    const moveResult = await tx.moveDistinctIds(sourcePerson, targetPerson)

                    // These should not execute
                    await tx.deletePerson(sourcePerson)
                    await tx.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePerson.id, targetPerson.id)

                    return moveResult
                })
            ).rejects.toThrow('simulated moveDistinctIds failure')

            spy.mockRestore()

            // Verify source person still exists
            const sourceCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [sourceUuid],
                'verify-source-not-deleted'
            )
            expect(sourceCheck.rows.length).toBe(1)

            // Verify distinct IDs remain with their original persons
            await verifyDistinctIdsForPerson(team.id, sourcePerson.id, sourceUuid, ['merge-fail-source'])
            await verifyDistinctIdsForPerson(team.id, targetPerson.id, targetUuid, ['merge-fail-target'])
        })

        it('should handle creation conflict within transaction correctly', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const uuid1 = '77777777-7777-7777-7777-777777777777'
            const uuid2 = '88888888-8888-8888-8888-888888888888'

            // Create first person with a distinct ID
            await repository.createPerson(createdAt, { first: true }, {}, {}, team.id, null, false, uuid1, [
                { distinctId: 'conflict-did', version: 0 },
            ])

            // Try to create another person with the same distinct ID in a transaction
            // Should now return a failure result instead of throwing
            const result = await repository.inTransaction('test-conflict', async (tx) => {
                const createResult = await tx.createPerson(
                    createdAt,
                    { second: true },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuid2,
                    [{ distinctId: 'conflict-did', version: 0 }]
                )

                // The transaction should handle the conflict gracefully
                expect(createResult.success).toBe(false)
                if (!createResult.success) {
                    expect(createResult.error).toBe('CreationConflict')
                }

                return createResult
            })

            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error).toBe('CreationConflict')
            }

            // Verify second person was not created
            const secondCheck = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid2],
                'verify-second-not-created'
            )
            expect(secondCheck.rows.length).toBe(0)
        })

        it('should propagate errors correctly through transaction boundaries', async () => {
            const team = await getFirstTeam(postgres)
            const customError = new Error('Custom transaction error')

            await expect(
                repository.inTransaction('test-error-propagation', async (tx) => {
                    await tx.addPersonlessDistinctIdForMerge(team.id, 'error-test-did')

                    throw customError
                })
            ).rejects.toThrow('Custom transaction error')

            const check = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE distinct_id = $1',
                ['error-test-did'],
                'verify-personless-rollback'
            )
            expect(check.rows.length).toBe(0)
        })

        it('should handle primary database failure within transaction', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const uuid = '99999999-9999-9999-9999-999999999999'

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary database failure in transaction'),
                'updatePerson'
            )

            await expect(
                repository.inTransaction('test-primary-failure', async (tx) => {
                    const createResult = await tx.createPerson(
                        createdAt,
                        { initial: true },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuid,
                        [{ distinctId: 'primary-fail-did', version: 0 }]
                    )

                    if (!createResult.success) {
                        throw new Error('Failed to create person')
                    }

                    await tx.updatePerson(createResult.person, { properties: { updated: true } })

                    return createResult.person
                })
            ).rejects.toThrow('primary database failure in transaction')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-tx-rollback',
                'verify-secondary-tx-rollback'
            )
        })

        it('should handle secondary database failure within transaction', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary database failure in transaction'),
                'insertPerson'
            )

            await expect(
                repository.inTransaction('test-secondary-failure', async (tx) => {
                    const createResult = await tx.createPerson(
                        createdAt,
                        { initial: true },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        uuid,
                        [{ distinctId: 'secondary-fail-did', version: 0 }]
                    )

                    return createResult
                })
            ).rejects.toThrow('secondary database failure in transaction')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-no-commit',
                'verify-secondary-no-commit'
            )
        })

        it('should throw error when moveDistinctIds has mismatched results in transaction', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const sourceUuid = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
            const targetUuid = 'cccccccc-cccc-cccc-cccc-cccccccccccc'

            const { person: sourcePerson } = (await repository.createPerson(
                createdAt,
                { source: true },
                {},
                {},
                team.id,
                null,
                false,
                sourceUuid,
                [{ distinctId: 'mismatch-source', version: 0 }]
            )) as any

            const { person: targetPerson } = (await repository.createPerson(
                createdAt,
                { target: true },
                {},
                {},
                team.id,
                null,
                false,
                targetUuid,
                [{ distinctId: 'mismatch-target', version: 0 }]
            )) as any

            const spy = jest.spyOn((repository as any).secondaryRepo, 'moveDistinctIds')
            spy.mockResolvedValueOnce({ success: false, error: 'TargetPersonDeleted' })

            await expect(
                repository.inTransaction('test-mismatch', async (tx) => {
                    const result = await tx.moveDistinctIds(sourcePerson, targetPerson)
                    return result
                })
            ).rejects.toThrow('DualWrite moveDistinctIds mismatch')

            spy.mockRestore()

            await verifyDistinctIdsForPerson(team.id, sourcePerson.id, sourceUuid, ['mismatch-source'])
            await verifyDistinctIdsForPerson(team.id, targetPerson.id, targetUuid, ['mismatch-target'])
        })

        it('should handle moveDistinctIds when both databases fail identically within transaction', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const sourceUuid = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
            const targetUuid = 'ffffffff-ffff-ffff-ffff-ffffffffffff'

            const { person: sourcePerson } = (await repository.createPerson(
                createdAt,
                { source: true },
                {},
                {},
                team.id,
                null,
                false,
                sourceUuid,
                [{ distinctId: 'identical-fail-source', version: 0 }]
            )) as any

            const { person: targetPerson } = (await repository.createPerson(
                createdAt,
                { target: true },
                {},
                {},
                team.id,
                null,
                false,
                targetUuid,
                [{ distinctId: 'identical-fail-target', version: 0 }]
            )) as any

            const primarySpy = jest.spyOn((repository as any).primaryRepo, 'moveDistinctIds')
            const secondarySpy = jest.spyOn((repository as any).secondaryRepo, 'moveDistinctIds')
            primarySpy.mockResolvedValueOnce({ success: false, error: 'TargetPersonDeleted' })
            secondarySpy.mockResolvedValueOnce({ success: false, error: 'TargetPersonDeleted' })

            const result = await repository.inTransaction('test-identical-failure', async (tx) => {
                const moveResult = await tx.moveDistinctIds(sourcePerson, targetPerson)
                expect(moveResult.success).toBe(false)
                if (!moveResult.success) {
                    expect(moveResult.error).toBe('TargetPersonDeleted')
                }
                return moveResult
            })

            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error).toBe('TargetPersonDeleted')
            }

            primarySpy.mockRestore()
            secondarySpy.mockRestore()
        })

        it('should prevent or handle nested inTransaction calls gracefully', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            // Test what happens when inTransaction is called within another inTransaction
            // This could happen if code inadvertently nests transaction calls

            let innerTransactionExecuted = false
            let outerTransactionCompleted = false
            let errorCaught: Error | null = null

            try {
                await repository.inTransaction('outer-transaction', async (outerTx) => {
                    // Create a person in the outer transaction
                    const outerResult = await outerTx.createPerson(
                        createdAt,
                        { level: 'outer' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        '11111111-0000-0000-0000-000000000001',
                        [{ distinctId: 'outer-tx-did', version: 0 }]
                    )

                    if (!outerResult.success) {
                        throw new Error('Outer transaction creation failed')
                    }

                    // Attempt to nest another transaction
                    // This should either fail or be handled gracefully
                    try {
                        await repository.inTransaction('inner-transaction', async (innerTx) => {
                            innerTransactionExecuted = true
                            const innerResult = await innerTx.createPerson(
                                createdAt,
                                { level: 'inner' },
                                {},
                                {},
                                team.id,
                                null,
                                false,
                                '22222222-0000-0000-0000-000000000002',
                                [{ distinctId: 'inner-tx-did', version: 0 }]
                            )
                            return innerResult
                        })
                    } catch (e: any) {
                        // Nested transaction might fail
                        errorCaught = e
                    }

                    outerTransactionCompleted = true
                    return outerResult
                })
            } catch (e: any) {
                errorCaught = e
            }

            // Check the behavior - either:
            // 1. Nested transactions are not supported and throw an error
            // 2. They work but use savepoints
            // 3. They work but are actually part of the same transaction

            if (errorCaught) {
                // If an error was thrown, it's likely because nested transactions aren't supported
                // This is actually good behavior to prevent transaction confusion
                expect(errorCaught.message).toMatch(/transaction|nested|already|active/i)
            } else {
                // If no error, check if both persons were created
                const outerPerson = await repository.fetchPerson(team.id, 'outer-tx-did')
                const innerPerson = await repository.fetchPerson(team.id, 'inner-tx-did')

                if (innerTransactionExecuted) {
                    // Both should exist if nested transactions are handled
                    expect(outerPerson).toBeDefined()
                    expect(innerPerson).toBeDefined()
                }
                expect(outerTransactionCompleted).toBe(true)
            }
        })

        it('should propagate errors correctly through transaction boundaries', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            // Test various error types and their propagation

            // Test 1: Custom application error
            const customError = new Error('Custom application error in transaction')
            await expect(
                repository.inTransaction('test-custom-error', async (tx) => {
                    await tx.createPerson(
                        createdAt,
                        { test: 'error-propagation' },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        '33333333-0000-0000-0000-000000000003',
                        [{ distinctId: 'error-test-1', version: 0 }]
                    )
                    throw customError
                })
            ).rejects.toThrow('Custom application error in transaction')

            // Verify the person was not created due to rollback
            const person1 = await repository.fetchPerson(team.id, 'error-test-1')
            expect(person1).toBeUndefined()

            // Test 2: Database constraint error
            const uuid4 = '44444444-0000-0000-0000-000000000004'
            await repository.createPerson(createdAt, { existing: true }, {}, {}, team.id, null, false, uuid4, [
                { distinctId: 'constraint-test', version: 0 },
            ])

            // Try to create with same distinct ID in transaction
            const result = await repository.inTransaction('test-constraint-error', async (tx) => {
                const result = await tx.createPerson(
                    createdAt,
                    { duplicate: true },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    '55555555-0000-0000-0000-000000000005',
                    [{ distinctId: 'constraint-test', version: 0 }]
                )
                return result
            })

            // CreationConflict should be returned, not thrown
            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error).toBe('CreationConflict')
            }

            // Test 3: Error in the middle of multiple operations
            await expect(
                repository.inTransaction('test-mid-operation-error', async (tx) => {
                    // First operation succeeds
                    const person = await tx.createPerson(
                        createdAt,
                        { step: 1 },
                        {},
                        {},
                        team.id,
                        null,
                        false,
                        '66666666-0000-0000-0000-000000000006',
                        [{ distinctId: 'multi-op-1', version: 0 }]
                    )

                    if (!person.success) {
                        throw new Error('First operation failed')
                    }

                    // Second operation succeeds
                    await tx.addDistinctId(person.person!, 'multi-op-2', 1)

                    // Third operation fails
                    throw new Error('Intentional failure after partial success')
                })
            ).rejects.toThrow('Intentional failure after partial success')

            // Verify all operations were rolled back
            const person2 = await repository.fetchPerson(team.id, 'multi-op-1')
            const person3 = await repository.fetchPerson(team.id, 'multi-op-2')
            expect(person2).toBeUndefined()
            expect(person3).toBeUndefined()
        })

        it('should handle mixed direct and transactional calls correctly', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()

            // Create a person outside transaction
            const outsideResult = await repository.createPerson(
                createdAt,
                { location: 'outside' },
                {},
                {},
                team.id,
                null,
                false,
                '77777777-0000-0000-0000-000000000007',
                [{ distinctId: 'outside-tx', version: 0 }]
            )

            expect(outsideResult.success).toBe(true)
            if (!outsideResult.success) {
                throw new Error('Expected person creation to succeed')
            }
            const outsidePerson = outsideResult.person

            // Now use it within a transaction
            const txResult = await repository.inTransaction('test-mixed-calls', async (tx) => {
                // Update the person created outside
                const [updated] = await tx.updatePerson(outsidePerson, {
                    properties: { location: 'updated-inside', new_prop: 'added' },
                })

                // Add a distinct ID
                await tx.addDistinctId(updated, 'added-in-tx', 1)

                // Create a new person within the transaction
                const newPerson = await tx.createPerson(
                    createdAt,
                    { location: 'inside' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    '88888888-0000-0000-0000-000000000008',
                    [{ distinctId: 'inside-tx', version: 0 }]
                )

                return { updated, newPerson }
            })

            // Verify the mixed operations worked
            const updatedOutside = await repository.fetchPerson(team.id, 'outside-tx')
            const addedDistinctId = await repository.fetchPerson(team.id, 'added-in-tx')
            const insidePerson = await repository.fetchPerson(team.id, 'inside-tx')

            expect(updatedOutside).toBeDefined()
            expect(updatedOutside?.properties.location).toBe('updated-inside')
            expect(updatedOutside?.properties.new_prop).toBe('added')
            expect(addedDistinctId?.id).toBe(outsidePerson.id)
            expect(insidePerson).toBeDefined()
            expect(txResult.newPerson.success).toBe(true)
        })

        it('should enforce version synchronization in updatePerson within transaction', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-20T10:30:00.000Z').toUTC()
            const uuid = 'dddddddd-dddd-dddd-dddd-dddddddddddd'

            const { person } = (await repository.createPerson(
                createdAt,
                { initial: 'value' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId: 'version-sync-did', version: 0 }]
            )) as any

            const result = await repository.inTransaction('test-version-sync', async (tx) => {
                const [updatedPerson] = await tx.updatePerson(person, { properties: { updated: 'value' } })
                return updatedPerson
            })

            // Verify version was properly synchronized between primary and secondary
            const primaryVersion = await postgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT version FROM posthog_person WHERE uuid = $1',
                [uuid],
                'check-primary-version'
            )
            const secondaryVersion = await migrationPostgres.query(
                PostgresUse.PERSONS_READ,
                'SELECT version FROM posthog_person WHERE uuid = $1',
                [uuid],
                'check-secondary-version'
            )

            // Both should have the same version (primary's version + 1)
            expect(Number(primaryVersion.rows[0].version)).toBe(person.version + 1)
            expect(Number(secondaryVersion.rows[0].version)).toBe(person.version + 1)
            expect(result.version).toBe(person.version + 1)

            // Verify that both databases have the same version even though secondary is forced to match primary
            expect(Number(primaryVersion.rows[0].version)).toBe(Number(secondaryVersion.rows[0].version))
        })
    })
})
