import fs from 'fs'
import { DateTime } from 'luxon'
import path from 'path'

import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'

import { PostgresDualWritePersonRepository } from './postgres-dualwrite-person-repository'

jest.mock('../../../../utils/logger')

describe('PostgresDualWritePersonRepository', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let migrationPostgres: PostgresRouter
    let repository: PostgresDualWritePersonRepository

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

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        migrationPostgres = hub.db.postgresPersonMigration
        await setupMigrationDb()

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

    async function getFirstTeam(hub: Hub): Promise<Team> {
        const teams = await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            'SELECT * FROM posthog_team LIMIT 1',
            [],
            'getFirstTeam'
        )
        return teams.rows[0]
    }
    describe('createPerson()', () => {
        it('createPerson writes to both primary and secondary', async () => {
            const team = await getFirstTeam(hub)
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
        it('createPerson rolls back both when secondary write fails', async () => {
            const team = await getFirstTeam(hub)
            const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
            const uuid = '88888888-8888-8888-8888-888888888888'
            // Force the internal secondaryRepo.createPerson to throw to simulate failure during the 2PC boundary
            const spy = jest
                .spyOn((repository as any).secondaryRepo, 'createPerson')
                .mockRejectedValue(new Error('simulated secondary failure'))

            await expect(
                repository.createPerson(createdAt, { y: 1 }, {}, {}, team.id, null, false, uuid, [
                    { distinctId: 'dw-fail' },
                ])
            ).rejects.toThrow('simulated secondary failure')

            spy.mockRestore()

            // Verify no person exists in either database after rollback
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
    })

    describe('updatePerson()', () => {
        it('replicates to secondary (happy path)', async () => {
            const team = await getFirstTeam(hub)
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

        it('rolls back both when secondary update fails (sad path)', async () => {
            const team = await getFirstTeam(hub)
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
    })

    describe('deletePerson()', () => {
        it('removes from both (happy path)', async () => {
            const team = await getFirstTeam(hub)
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

        it('rolls back both when secondary delete fails (sad path)', async () => {
            const team = await getFirstTeam(hub)
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
    })

    describe('addDistinctId()', () => {
        it('writes to both (happy path)', async () => {
            const team = await getFirstTeam(hub)
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

        it('rolls back both when secondary addDistinctId fails (sad path)', async () => {
            const team = await getFirstTeam(hub)
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
    })

    describe('moveDistinctIds()', () => {
        it('affects both sides (happy path)', async () => {
            const team = await getFirstTeam(hub)
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

        it('rolls back both when secondary moveDistinctIds fails (sad path)', async () => {
            const team = await getFirstTeam(hub)
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

            // Verify source and target mappings unchanged
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
    })

    describe('addPersonlessDistinctId()', () => {
        it('writes to both (happy path)', async () => {
            const team = await getFirstTeam(hub)
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

        it('rolls back both when secondary addPersonlessDistinctId fails (sad path)', async () => {
            const team = await getFirstTeam(hub)
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
    })

    describe('addPersonlessDistinctIdForMerge()', () => {
        it('writes to both (happy path)', async () => {
            const team = await getFirstTeam(hub)
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

        it('rolls back both when secondary addPersonlessDistinctIdForMerge fails (sad path)', async () => {
            const team = await getFirstTeam(hub)
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
    })

    describe('updatePersonAssertVersion()', () => {
        it('updates secondary on primary success (happy path)', async () => {
            const team = await getFirstTeam(hub)
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

        it('does not rollback primary when secondary fails (sad path, non-2PC)', async () => {
            const team = await getFirstTeam(hub)
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
})
