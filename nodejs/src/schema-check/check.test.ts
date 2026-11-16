import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'

import {
    AppliedMigration,
    MigrationStore,
    SqlxMigrationRow,
    SqlxMigrationStore,
    evaluateSqlxRows,
    findMissingRequirements,
} from './check'
import { CliDependencies, EXIT_ERROR, EXIT_MISSING, EXIT_SATISFIED, runCli } from './cli'
import { DjangoRequirement, SqlxRequirement, buildManifest } from './manifest'

const WORKFLOWS: DjangoRequirement = {
    kind: 'django',
    database: 'default',
    app: 'workflows',
    migration: '0040_frequency_cap_hold',
}
const TRACING_SQUASH: DjangoRequirement = {
    kind: 'django',
    database: 'default',
    app: 'tracing',
    migration: '0001_squash_initial',
    replaces: ['0001_initial', '0002_span_kind'],
}

const CYCLOTRON: SqlxRequirement = { kind: 'sqlx', database: 'cyclotron-node', version: 20260201000001 }

class FakeSqlxMigrationStore implements SqlxMigrationStore {
    constructor(private readonly rows: SqlxMigrationRow[]) {}

    fetchRows(): Promise<SqlxMigrationRow[]> {
        return Promise.resolve(this.rows)
    }
}

class FakeMigrationStore implements MigrationStore {
    fetchAppliedCalls = 0

    constructor(private readonly appliedPerPoll: AppliedMigration[][]) {}

    fetchApplied(): Promise<AppliedMigration[]> {
        const index = Math.min(this.fetchAppliedCalls, this.appliedPerPoll.length - 1)
        this.fetchAppliedCalls += 1
        return Promise.resolve(this.appliedPerPoll[index])
    }

    fetchLatestApplied(): Promise<Map<string, string>> {
        return Promise.resolve(new Map([['workflows', '0039_previous']]))
    }
}

describe('schema check', () => {
    describe('findMissingRequirements', () => {
        it.each<[string, DjangoRequirement, AppliedMigration[], boolean]>([
            ['leaf applied', WORKFLOWS, [{ app: 'workflows', name: '0040_frequency_cap_hold' }], false],
            ['leaf not applied', WORKFLOWS, [{ app: 'workflows', name: '0039_previous' }], true],
            ['same name in another app', WORKFLOWS, [{ app: 'posthog', name: '0040_frequency_cap_hold' }], true],
            ['squash row applied', TRACING_SQUASH, [{ app: 'tracing', name: '0001_squash_initial' }], false],
            [
                'every replaced migration applied',
                TRACING_SQUASH,
                [
                    { app: 'tracing', name: '0001_initial' },
                    { app: 'tracing', name: '0002_span_kind' },
                ],
                false,
            ],
            ['only some replaced migrations applied', TRACING_SQUASH, [{ app: 'tracing', name: '0001_initial' }], true],
        ])('%s', (_case, requirement, applied, expectMissing) => {
            expect(findMissingRequirements([requirement], applied)).toEqual(expectMissing ? [requirement] : [])
        })
    })

    describe('evaluateSqlxRows', () => {
        it.each<[string, SqlxMigrationRow[], string]>([
            ['version applied', [{ version: 20260201000001, success: true }], 'satisfied'],
            ['version not applied', [], 'missing'],
            [
                'a failed migration on the database',
                [
                    { version: 20260201000001, success: true },
                    { version: 20260301000001, success: false },
                ],
                'dirty',
            ],
        ])('%s', (_case, rows, expectedStatus) => {
            expect(evaluateSqlxRows(CYCLOTRON, rows).status).toBe(expectedStatus)
        })
    })

    describe('runCli', () => {
        let dir: string
        let output: string[]

        const writeManifest = (content: string): string => {
            const manifestPath = path.join(dir, 'schema-requirements.json')
            writeFileSync(manifestPath, content)
            return manifestPath
        }

        const makeDeps = (
            store: MigrationStore,
            clock?: { now: number },
            sqlxStore: SqlxMigrationStore = new FakeSqlxMigrationStore([])
        ): CliDependencies => ({
            createStore: () => store,
            createSqlxStore: () => sqlxStore,
            sleep: (ms) => {
                if (clock) {
                    clock.now += ms
                }
                return Promise.resolve()
            },
            log: (message) => output.push(message),
            logError: (message) => output.push(message),
        })

        beforeEach(() => {
            dir = mkdtempSync(path.join(tmpdir(), 'schema-check-cli-'))
            output = []
        })

        afterEach(() => {
            rmSync(dir, { recursive: true, force: true })
            jest.restoreAllMocks()
        })

        it.each([
            ['missing', null],
            ['unparseable', '{not json'],
            ['empty', JSON.stringify({ schema_version: 1, digest: 'x', requirements: [] })],
            [
                'of an unknown kind',
                JSON.stringify({ schema_version: 1, digest: 'x', requirements: [{ ...WORKFLOWS, kind: 'flyway' }] }),
            ],
        ])('exits with an error when the manifest is %s', async (_case, content) => {
            const manifestPath = content === null ? path.join(dir, 'absent.json') : writeManifest(content)
            const store = new FakeMigrationStore([[]])

            const code = await runCli(['--manifest', manifestPath], { DATABASE_URL: 'postgres://x' }, makeDeps(store))

            expect(code).toBe(EXIT_ERROR)
            expect(store.fetchAppliedCalls).toBe(0)
        })

        it('exits 1 and names the missing migration and the latest applied one', async () => {
            const manifestPath = writeManifest(JSON.stringify(buildManifest([WORKFLOWS], 'abc123')))
            const store = new FakeMigrationStore([[{ app: 'workflows', name: '0039_previous' }]])

            const code = await runCli(['--manifest', manifestPath], { DATABASE_URL: 'postgres://x' }, makeDeps(store))

            expect(code).toBe(EXIT_MISSING)
            expect(output).toContain('  needs workflows.0040_frequency_cap_hold, has up to 0039_previous')
        })

        it.each<[string, Record<string, string>, SqlxMigrationRow[], string]>([
            ['missing', { CYCLOTRON_NODE_DATABASE_URL: 'postgres://c' }, [], 'cyclotron-node missing'],
            [
                'dirty',
                { CYCLOTRON_NODE_DATABASE_URL: 'postgres://c' },
                [{ version: 1, success: false }],
                'cyclotron-node dirty',
            ],
            ['not configured for this app', {}, [], 'cyclotron-node skipped'],
        ])('logs a %s sqlx database and still exits 0', async (_case, extraEnv, sqlxRows, expectedLog) => {
            const manifestPath = writeManifest(JSON.stringify(buildManifest([WORKFLOWS, CYCLOTRON], null)))
            const store = new FakeMigrationStore([[{ app: 'workflows', name: '0040_frequency_cap_hold' }]])

            const code = await runCli(
                ['--manifest', manifestPath],
                { DATABASE_URL: 'postgres://x', ...extraEnv },
                makeDeps(store, undefined, new FakeSqlxMigrationStore(sqlxRows))
            )

            expect(code).toBe(EXIT_SATISFIED)
            expect(output.some((line) => line.includes(expectedLog))).toBe(true)
        })

        it('keeps polling until the migration lands within --wait-seconds', async () => {
            const clock = { now: 0 }
            jest.spyOn(Date, 'now').mockImplementation(() => clock.now)
            const manifestPath = writeManifest(JSON.stringify(buildManifest([WORKFLOWS], null)))
            const store = new FakeMigrationStore([[], [], [{ app: 'workflows', name: '0040_frequency_cap_hold' }]])

            const code = await runCli(
                ['--manifest', manifestPath, '--wait-seconds', '60', '--poll-interval-seconds', '15'],
                { DATABASE_URL: 'postgres://x' },
                makeDeps(store, clock)
            )

            expect(code).toBe(EXIT_SATISFIED)
            expect(store.fetchAppliedCalls).toBe(3)
        })

        it('gives up with exit 1 once --wait-seconds passes', async () => {
            const clock = { now: 0 }
            jest.spyOn(Date, 'now').mockImplementation(() => clock.now)
            const manifestPath = writeManifest(JSON.stringify(buildManifest([WORKFLOWS], null)))
            const store = new FakeMigrationStore([[]])

            const code = await runCli(
                ['--manifest', manifestPath, '--wait-seconds', '40', '--poll-interval-seconds', '15'],
                { DATABASE_URL: 'postgres://x' },
                makeDeps(store, clock)
            )

            expect(code).toBe(EXIT_MISSING)
            // Polls at 0 s, 15 s, 30 s and 40 s, where the last sleep is cut to the remaining 10 s.
            expect(store.fetchAppliedCalls).toBe(4)
        })
    })
})
