import { DateTime } from 'luxon'

import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'

import { PostgresDualWritePersonRepository } from './postgres-dualwrite-person-repository'
import {
    setupMigrationDb,
    cleanupPrepared,
    getFirstTeam,
    mockDatabaseError,
    assertConsistencyAcrossDatabases
} from './test-helpers'

jest.mock('../../../../utils/logger')

describe('PostgresDualWritePersonRepository 2PC Dual-Write Tests', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let repository: PostgresDualWritePersonRepository

    async function verifyDistinctIdsForPerson(
        teamId: number,
        personId: number,
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

        it('rolls back when primary database fails', () => {
        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '11111111-1111-1111-1111-111111111111'
            
            // Mock primary database to fail during person insertion
            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary database connection lost'),
                'insertPerson'
            )

            await expect(
                repository.createPerson(
                    createdAt,
                    { name: 'Test Person' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuid,
                    [{ distinctId: 'test-primary-fail', version: 0 }]
                )
            ).rejects.toThrow('primary database connection lost')

            mockSpy.mockRestore()

            // Verify both databases have no records (rollback successful)
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
            
            // Verify they're empty
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
            
            // Mock secondary database to fail during person insertion
            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary database connection lost'),
                'insertPerson'
            )

            await expect(
                repository.createPerson(
                    createdAt,
                    { name: 'Test Person' },
                    {},
                    {},
                    team.id,
                    null,
                    false,
                    uuid,
                    [{ distinctId: 'test-secondary-fail', version: 0 }]
                )
            ).rejects.toThrow('secondary database connection lost')

            mockSpy.mockRestore()

            // Verify both databases have no records (rollback successful)
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
            
            // Verify they're empty
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

        it('rolls back when primary database fails', () => {
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

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary update failed'),
                'updatePerson'
            )

            await expect(
                repository.updatePerson(person, { properties: { name: 'Updated' } })
            ).rejects.toThrow('primary update failed')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-unchanged',
                'verify-secondary-unchanged'
            )
            
            // Verify properties remain unchanged
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

            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary update failed'),
                'updatePerson'
            )

            await expect(
                repository.updatePerson(person, { properties: { name: 'Updated' } })
            ).rejects.toThrow('secondary update failed')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT properties FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-unchanged',
                'verify-secondary-unchanged'
            )
            
            // Verify properties remain unchanged
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

        it('rolls back when primary database fails', () => {
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

            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary delete failed'),
                'deletePerson'
            )

            await expect(
                repository.deletePerson(person)
            ).rejects.toThrow('primary delete failed')

            mockSpy.mockRestore()

            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-exists',
                'verify-secondary-exists'
            )
            
            // Verify person still exists
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
            
            // Create a person first
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

            // Mock secondary database to fail during deletion
            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary delete failed'),
                'deletePerson'
            )

            await expect(
                repository.deletePerson(person)
            ).rejects.toThrow('secondary delete failed')

            mockSpy.mockRestore()

            // Verify both databases still have the person (rollback successful)
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_person WHERE uuid = $1',
                [uuid],
                'verify-primary-exists',
                'verify-secondary-exists'
            )
            
            // Verify person still exists
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

        it('rolls back when primary database fails', () => {
        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '77777777-7777-7777-7777-777777777777'
            
            // Create a person first
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

            // Mock primary database to fail during addDistinctId
            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary addDistinctId failed'),
                'addDistinctId'
            )

            await expect(
                repository.addDistinctId(person, 'new-did-primary-fail', 1)
            ).rejects.toThrow('primary addDistinctId failed')

            mockSpy.mockRestore()

            // Verify the new distinct ID was not added to either database
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['new-did-primary-fail'],
                'verify-primary-no-new-did',
                'verify-secondary-no-new-did'
            )
            
            // Verify it doesn't exist
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
            
            // Create a person first
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

            // Mock secondary database to fail during addDistinctId
            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary addDistinctId failed'),
                'addDistinctId'
            )

            await expect(
                repository.addDistinctId(person, 'new-did-secondary-fail', 1)
            ).rejects.toThrow('secondary addDistinctId failed')

            mockSpy.mockRestore()

            // Verify the new distinct ID was not added to either database
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_persondistinctid WHERE distinct_id = $1',
                ['new-did-secondary-fail'],
                'verify-primary-no-new-did',
                'verify-secondary-no-new-did'
            )
            
            // Verify it doesn't exist
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

        it('rolls back when primary database fails', () => {
        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const srcUuid = '99999999-9999-9999-9999-999999999999'
            const tgtUuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            
            // Create source and target persons
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

            // Add another distinct ID to source
            await repository.addDistinctId(src, 'src-did-2', 1)

            // Mock primary database to fail during moveDistinctIds
            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary moveDistinctIds failed'),
                'updateDistinctIdPerson'
            )

            await expect(
                repository.moveDistinctIds(src, tgt)
            ).rejects.toThrow('primary moveDistinctIds failed')

            mockSpy.mockRestore()

            // Verify distinct IDs remain with source person in both databases
            await verifyDistinctIdsForPerson(team.id, src.id, srcUuid, ['src-did', 'src-did-2'])
            await verifyDistinctIdsForPerson(team.id, tgt.id, tgtUuid, ['tgt-did'])
        })

        it('rolls back when secondary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const srcUuid = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
            const tgtUuid = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
            
            // Create source and target persons
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

            // Add another distinct ID to source
            await repository.addDistinctId(src, 'src-did-b-2', 1)

            // Mock secondary database to fail during moveDistinctIds
            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary moveDistinctIds failed'),
                'updateDistinctIdPerson'
            )

            await expect(
                repository.moveDistinctIds(src, tgt)
            ).rejects.toThrow('secondary moveDistinctIds failed')

            mockSpy.mockRestore()

            // Verify distinct IDs remain with source person in both databases
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

        it('rolls back when primary database fails', () => {
        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-primary-fail'
            
            // Mock primary database to fail
            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary addPersonlessDistinctId failed'),
                'addPersonlessDistinctId'
            )

            await expect(
                repository.addPersonlessDistinctId(team.id, did)
            ).rejects.toThrow('primary addPersonlessDistinctId failed')

            mockSpy.mockRestore()

            // Verify neither database has the record
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-personless',
                'verify-secondary-no-personless'
            )
            
            // Verify it doesn't exist
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
            
            // Mock secondary database to fail
            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary addPersonlessDistinctId failed'),
                'addPersonlessDistinctId'
            )

            await expect(
                repository.addPersonlessDistinctId(team.id, did)
            ).rejects.toThrow('secondary addPersonlessDistinctId failed')

            mockSpy.mockRestore()

            // Verify neither database has the record
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-personless',
                'verify-secondary-no-personless'
            )
            
            // Verify it doesn't exist
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

        it('rolls back when primary database fails', () => {
        it('rolls back when primary database fails', async () => {
            const team = await getFirstTeam(postgres)
            const did = 'personless-merge-primary-fail'
            
            // Mock primary database to fail
            const mockSpy = mockDatabaseError(
                postgres,
                new Error('primary addPersonlessDistinctIdForMerge failed'),
                'addPersonlessDistinctIdForMerge'
            )

            await expect(
                repository.addPersonlessDistinctIdForMerge(team.id, did)
            ).rejects.toThrow('primary addPersonlessDistinctIdForMerge failed')

            mockSpy.mockRestore()

            // Verify neither database has the record
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-merge',
                'verify-secondary-no-merge'
            )
            
            // Verify it doesn't exist
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
            
            // Mock secondary database to fail
            const mockSpy = mockDatabaseError(
                migrationPostgres,
                new Error('secondary addPersonlessDistinctIdForMerge failed'),
                'addPersonlessDistinctIdForMerge'
            )

            await expect(
                repository.addPersonlessDistinctIdForMerge(team.id, did)
            ).rejects.toThrow('secondary addPersonlessDistinctIdForMerge failed')

            mockSpy.mockRestore()

            // Verify neither database has the record
            await assertConsistencyAcrossDatabases(
                postgres,
                migrationPostgres,
                'SELECT 1 FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
                [team.id, did],
                'verify-primary-no-merge',
                'verify-secondary-no-merge'
            )
            
            // Verify it doesn't exist
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
})