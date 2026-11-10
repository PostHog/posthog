import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'

import {
    AppliedMigration,
    MigrationStore,
    SqlxMigrationRow,
    SqlxMigrationStore,
    SqlxShadowResult,
    evaluateSqlxRows,
    findMissingRequirements,
} from './check'
import { CliDependencies, EXIT_ERROR, EXIT_MISSING, EXIT_SATISFIED, runCli } from './cli'
import { DjangoRequirement, SqlxRequirement, buildManifest } from './manifest'
import { renderMetrics } from './metrics-push'

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

const CYCLOTRON: SqlxRequirement = {
    kind: 'sqlx',
    database: 'cyclotron-node',
    versions: [20260101000001, 20260201000001],
}
const PERSONS: SqlxRequirement = { kind: 'sqlx', database: 'persons', versions: [20250101000001] }

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
            [
                'every version applied',
                [
                    { version: 20260101000001, success: true },
                    { version: 20260201000001, success: true },
                ],
                'satisfied',
            ],
            ['a lower version merged late is not applied', [{ version: 20260201000001, success: true }], 'missing'],
            ['no version applied', [], 'missing'],
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

    describe('renderMetrics', () => {
        const sqlxResult = (requirement: SqlxRequirement, status: SqlxShadowResult['status']): SqlxShadowResult => ({
            requirement,
            status,
            detail: '',
        })

        it.each<[string, number, SqlxShadowResult[], string[]]>([
            [
                'satisfied',
                0,
                [sqlxResult(CYCLOTRON, 'satisfied')],
                ['node_schema_check_sqlx_missing{database="cyclotron-node"} 0'],
            ],
            [
                'missing',
                0,
                [sqlxResult(CYCLOTRON, 'missing')],
                ['node_schema_check_sqlx_missing{database="cyclotron-node"} 1'],
            ],
            [
                'skipped, errored and dirty databases omitted',
                1,
                [sqlxResult(PERSONS, 'skipped'), sqlxResult(CYCLOTRON, 'error'), sqlxResult(PERSONS, 'dirty')],
                [],
            ],
            ['no sqlx database checked', 2, [sqlxResult(PERSONS, 'skipped')], []],
        ])('%s', (_case, djangoExitCode, sqlx, expectedSqlxSamples) => {
            const samples = renderMetrics(djangoExitCode, sqlx, 1700000000)
                .split('\n')
                .filter((line) => line && !line.startsWith('#'))

            expect(samples).toEqual([
                'node_schema_check_last_run_timestamp_seconds 1700000000',
                `node_schema_check_django_exit_code ${djangoExitCode}`,
                ...expectedSqlxSamples,
            ])
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
            fetch: jest.fn(),
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
            [
                'a sqlx entry without versions',
                JSON.stringify({
                    schema_version: 1,
                    digest: 'x',
                    requirements: [WORKFLOWS, { ...CYCLOTRON, versions: [] }],
                }),
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
            ['replica-only', { PERSONS_READONLY_DATABASE_URL: 'postgres://p' }, [], 'persons missing'],
        ])('logs a %s sqlx database and still exits 0', async (_case, extraEnv, sqlxRows, expectedLog) => {
            const manifestPath = writeManifest(JSON.stringify(buildManifest([WORKFLOWS, CYCLOTRON, PERSONS], null)))
            const store = new FakeMigrationStore([[{ app: 'workflows', name: '0040_frequency_cap_hold' }]])

            const code = await runCli(
                ['--manifest', manifestPath],
                { DATABASE_URL: 'postgres://x', ...extraEnv },
                makeDeps(store, undefined, new FakeSqlxMigrationStore(sqlxRows))
            )

            expect(code).toBe(EXIT_SATISFIED)
            expect(output.some((line) => line.includes(expectedLog))).toBe(true)
        })

        it.each<[string, () => Promise<Response>]>([
            ['the Pushgateway is unreachable', () => Promise.reject(new Error('connect ECONNREFUSED'))],
            ['the Pushgateway answers 500', () => Promise.resolve(new Response('', { status: 500 }))],
        ])('keeps the exit code when %s', async (_case, respond) => {
            const manifestPath = writeManifest(JSON.stringify(buildManifest([WORKFLOWS], null)))
            const store = new FakeMigrationStore([[]])
            const fetchMock = jest.fn(respond)

            const code = await runCli(
                ['--manifest', manifestPath],
                {
                    DATABASE_URL: 'postgres://x',
                    SCHEMA_CHECK_PUSHGATEWAY_URL: 'http://pushgateway.example.com:9091/',
                    SCHEMA_CHECK_APP: 'ingestion events',
                },
                { ...makeDeps(store), fetch: fetchMock }
            )

            expect(code).toBe(EXIT_MISSING)
            expect(fetchMock).toHaveBeenCalledWith(
                'http://pushgateway.example.com:9091/metrics/job/node_schema_check/node_app/ingestion%20events',
                expect.objectContaining({ method: 'PUT' })
            )
            expect(output.some((line) => line.startsWith('Warning: schema check metrics push failed'))).toBe(true)
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
