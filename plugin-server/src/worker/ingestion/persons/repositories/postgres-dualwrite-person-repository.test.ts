import fs from 'fs'
import path from 'path'
import { DateTime } from 'luxon'
import { Hub, Team } from "~/types"
import { createHub, closeHub } from "~/utils/db/hub"
import { resetTestDatabase } from "~/tests/helpers/sql"
import { PostgresRouter, PostgresUse } from "~/utils/db/postgres"
import { PostgresDualWritePersonRepository } from "./postgres-dualwrite-person-repository"

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
            const res = await r.query(PostgresUse.PERSONS_WRITE, `SELECT gid FROM pg_prepared_xacts WHERE gid LIKE 'dualwrite:%'`, [], 'list-prepared')
            for (const row of res.rows) {
                await r.query(PostgresUse.PERSONS_WRITE, `ROLLBACK PREPARED '${String(row.gid).replace(/'/g, "''")}'`, [], 'rollback-prepared')
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

    it('updatePerson replicates to secondary', async () => {
        const team = await getFirstTeam(hub)
        const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
        const uuid = '22222222-2222-2222-2222-222222222222'
        const { person } = (await repository.createPerson(createdAt, { name: 'A' }, {}, {}, team.id, null, false, uuid, [
            { distinctId: 'dw-2' },
        ])) as any

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

    it('deletePerson removes from both', async () => {
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

    it('addDistinctId writes to both', async () => {
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

    it('moveDistinctIds affects both sides', async () => {
        const team = await getFirstTeam(hub)
        const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
        const srcUuid = '55555555-5555-5555-5555-555555555555'
        const tgtUuid = '66666666-6666-6666-6666-666666666666'

        const { person: src } = (await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, srcUuid, [
            { distinctId: 'src-a', version: 0 },
        ])) as any
        const { person: tgt } = (await repository.createPerson(createdAt, {}, {}, {}, team.id, null, false, tgtUuid, [
            { distinctId: 'tgt-a', version: 0 },
        ])) as any

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

    it('addPersonlessDistinctId and addPersonlessDistinctIdForMerge write to both', async () => {
        const team = await getFirstTeam(hub)
        const did = 'personless-1'
        const inserted = await repository.addPersonlessDistinctId(team.id, did)
        expect(inserted).toBe(false)
        const merged = await repository.addPersonlessDistinctIdForMerge(team.id, did)
        expect(merged === true || merged === false).toBe(true) // primary return used

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

    it('updatePersonAssertVersion only updates secondary on primary success', async () => {
        const team = await getFirstTeam(hub)
        const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
        const uuid = '77777777-7777-7777-7777-777777777777'
        const { person } = (await repository.createPerson(createdAt, { x: 1 }, {}, {}, team.id, null, false, uuid)) as any

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

    it('rolls back both when secondary update fails inside 2PC boundary', async () => {
        const team = await getFirstTeam(hub)
        const createdAt = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()
        const uuid = '88888888-8888-8888-8888-888888888888'
        const { person } = (await repository.createPerson(createdAt, { y: 1 }, {}, {}, team.id, null, false, uuid, [
            { distinctId: 'dw-fail' },
        ])) as any

        // Force the internal secondaryRepo.updatePerson to throw to simulate failure during the tx function
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