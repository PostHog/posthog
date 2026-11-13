import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'
import { deflateSync } from 'zlib'

import { CyclotronV2Manager } from '~/cdp/services/cyclotron-v2/manager'
import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'

import { RESIDENT_TEAMS_FROM, scratchSchema, withPostgres } from '../environment/stack'
import { main } from '../main'
import { EXIT_CODE } from '../runner/status'

const BACKLOG = {
    teams: 3,
    jobs: { hogflow: 200, email: 100 },
    stateBytes: { p50: 1000, p90: 4000, p99: 20000 },
    compressibility: 0.6,
    parkFor: '10080m',
    tolerance: 0.01,
}

describe('seed-backlog', () => {
    const jobs = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_backlog_${process.pid}`, [
        'cyclotron_jobs',
        'cyclotron_email_team_seq',
    ])
    let cacheHome: string
    let stderr: jest.SpyInstance

    const query = <T>(sql: string, params: unknown[] = []): Promise<T[]> =>
        withPostgres(async (client) => (await client.query(sql, params)).rows as T[], jobs.url)

    const seed = async (backlog: object | null = BACKLOG): Promise<number> => {
        const profile = path.join(cacheHome, 'profile.yaml')
        writeFileSync(profile, stringify({ name: 'resident', settings: {}, ...(backlog ? { backlog } : {}) }))
        return main(['seed-backlog', '--profile', profile], {
            ...process.env,
            XDG_CACHE_HOME: cacheHome,
            CYCLOTRON_NODE_DATABASE_URL: jobs.url,
        })
    }

    const manifestPath = (): string => path.join(cacheHome, 'posthog-scenarios', 'backlog.json')

    beforeAll(() => jobs.create())

    afterAll(() => jobs.drop())

    beforeEach(async () => {
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-backlog-'))
        jest.spyOn(process.stdout, 'write').mockReturnValue(true)
        stderr = jest.spyOn(process.stderr, 'write').mockReturnValue(true)
        await query('DROP TRIGGER IF EXISTS loses_rows ON cyclotron_jobs')
        await query('DELETE FROM cyclotron_jobs')
    })

    afterEach(() => {
        jest.restoreAllMocks()
        rmSync(cacheHome, { recursive: true, force: true })
    })

    it('parks each queue its jobs under reserved teams, with the state sizes and compressibility the profile asks for', async () => {
        const seededAt = Date.now()

        expect(await seed()).toBe(EXIT_CODE.passed)

        const rows = await query<{ queue_name: string; team_id: number; scheduled_ms: number; state: Buffer }>(
            'SELECT queue_name, team_id, (extract(epoch FROM scheduled) * 1000)::float8 AS scheduled_ms, state FROM cyclotron_jobs'
        )
        const sizes = rows.map(({ state }) => state.length).sort((a, b) => a - b)
        const quantile = (q: number): number => sizes[Math.ceil(q * sizes.length) - 1]
        const total = sizes.reduce((sum, size) => sum + size, 0)
        const deflated = rows.reduce((sum, { state }) => sum + deflateSync(state).length, 0)
        expect({
            perQueue: Object.fromEntries(
                Object.entries(Object.groupBy(rows, ({ queue_name }) => queue_name)).map(([queue, of]) => [
                    queue,
                    of!.length,
                ])
            ),
            teams: [...new Set(rows.map(({ team_id }) => team_id))].sort(),
            parkedPastTheHorizon: rows.every(({ scheduled_ms }) => scheduled_ms >= seededAt + 10080 * 60_000 - 1000),
            p50: Math.abs(quantile(0.5) / 1000 - 1) < 0.05,
            p90: Math.abs(quantile(0.9) / 4000 - 1) < 0.05,
            p99: Math.abs(quantile(0.99) / 20000 - 1) < 0.05,
            compressedShare: Math.abs(deflated / total - 0.4) < 0.05,
        }).toEqual({
            perQueue: { hogflow: 200, email: 100 },
            teams: [RESIDENT_TEAMS_FROM, RESIDENT_TEAMS_FROM + 1, RESIDENT_TEAMS_FROM + 2],
            parkedPastTheHorizon: true,
            p50: true,
            p90: true,
            p99: true,
            compressedShare: true,
        })
    })

    it('writes a manifest of the rows per team and status, with the table, index and TOAST bytes', async () => {
        expect(await seed()).toBe(EXIT_CODE.passed)

        const counted = await query<{ teamId: number; status: string; rows: number }>(
            `SELECT team_id AS "teamId", status::text AS status, count(*)::int AS rows
             FROM cyclotron_jobs GROUP BY 1, 2 ORDER BY 1, 2`
        )
        const manifest = parseJSON(readFileSync(manifestPath(), 'utf8')) as {
            rows: unknown[]
            bytes: Record<string, number>
        }
        expect(manifest.rows).toEqual(counted)
        expect(manifest.bytes).toEqual({
            table: expect.any(Number),
            indexes: expect.any(Number),
            toast: expect.any(Number),
        })
        expect(Object.values(manifest.bytes).every((bytes) => bytes > 0)).toBe(true)
    })

    it('replaces the residents of an earlier seed', async () => {
        await seed()

        expect(await seed({ ...BACKLOG, jobs: { email: 30 } })).toBe(EXIT_CODE.passed)
        expect(await query('SELECT queue_name, count(*)::int AS rows FROM cyclotron_jobs GROUP BY queue_name')).toEqual(
            [{ queue_name: 'email', rows: 30 }]
        )
    })

    it('fails and drops the earlier manifest when a queue holds fewer live rows than its tolerance allows', async () => {
        await seed()
        await query('DROP SEQUENCE IF EXISTS loses_every_tenth')
        await query('CREATE SEQUENCE loses_every_tenth')
        await query(
            `CREATE OR REPLACE FUNCTION loses_every_tenth() RETURNS trigger AS $$
             BEGIN
                 IF NEW.queue_name = 'hogflow' AND nextval('loses_every_tenth') % 10 = 0 THEN
                     RETURN NULL;
                 END IF;
                 RETURN NEW;
             END $$ LANGUAGE plpgsql`
        )
        await query(
            'CREATE TRIGGER loses_rows BEFORE INSERT ON cyclotron_jobs FOR EACH ROW EXECUTE FUNCTION loses_every_tenth()'
        )

        expect(await seed()).toBe(EXIT_CODE.invalid)
        expect(stderr.mock.calls.join('')).toContain(
            'hogflow: 180 live rows, outside 1% of the 200 the profile asks for'
        )
        expect(existsSync(manifestPath())).toBe(false)
    })

    it('holds no more than a batch of state in memory when the first batch goes out', async () => {
        const held: number[] = []
        const insert = CyclotronV2Manager.prototype.bulkCreateJobs
        jest.spyOn(CyclotronV2Manager.prototype, 'bulkCreateJobs').mockImplementation(function (
            this: CyclotronV2Manager,
            ...args
        ) {
            held.push(process.memoryUsage().arrayBuffers)
            return insert.apply(this, args)
        })
        const before = process.memoryUsage().arrayBuffers

        expect(
            await seed({
                ...BACKLOG,
                jobs: { hogflow: 1000 },
                stateBytes: { p50: 100_000, p90: 100_000, p99: 100_000 },
                compressibility: 1,
            })
        ).toBe(EXIT_CODE.passed)
        expect(held[0] - before).toBeLessThan(32 * 1024 * 1024)
    })

    it('reaches only the tables its scratch schema copies', async () => {
        await expect(query('SELECT 1 FROM _sqlx_migrations LIMIT 1')).rejects.toThrow('does not exist')
    })

    it('refuses a profile without a backlog', async () => {
        expect(await seed(null)).toBe(EXIT_CODE.invalid)
        expect(stderr.mock.calls.join('')).toContain('has no backlog to seed')
    })
})
