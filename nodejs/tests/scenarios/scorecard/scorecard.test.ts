import { execFileSync } from 'child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'fs'
import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { LoadedCard, load } from '../cards'
import { RunResult } from '../runner/runner'
import { exitCodeOf } from '../runner/status'
import { Provenance, provenanceOf } from './provenance'
import { scorecardOf } from './scorecard'
import { publish } from './write'

const TOKEN = 'phc_fake_scenario_runs_token'
const READ_KEY = 'phx_fake_scenario_runs_read_key'
const PROJECT_ID = '4242'
const RUN_ID = '6f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f'
const CAPTURE_KEYS = ['api_key', 'event', 'distinct_id', 'uuid', 'timestamp', 'properties']
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

const SMOKE: LoadedCard = load(path.join(__dirname, '..', 'cards', 'smoke.yaml'))

const PROVENANCE: Provenance = {
    headSha: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00',
    headDirty: true,
    runnerVersion: '1111111111111111111111111111111111111111',
    generatorVersion: '2222222222222222222222222222222222222222',
    valvesVersion: '4b825dc642cb6eb9a060e54bf8d69288fbee4904',
    hostCpu: 'Example CPU 3000 x 8',
    hostMemoryGb: 32,
}

const RESULT: RunResult = {
    runId: RUN_ID,
    status: 'failed',
    statusReason: 'at_least_once failed: run-x-3 email: the edge never received it',
    recorded: false,
    cardId: 'smoke',
    cardHash: SMOKE.cardHash,
    profileHash: SMOKE.profileHash,
    origin: 'local-agent',
    units: { targetUnits: 60, offeredUnits: 58 },
    convergence: { converged: true, unfinishedJobs: 0, unrecorded: [], tookMs: 4000 },
    invariants: [
        {
            name: 'at_least_once',
            passed: false,
            observed: 2,
            violation: 'run-x-3 email: the edge never received it',
            unitIds: ['run-x-3', 'run-x-7'],
        },
        { name: 'duplicate_sends', passed: true, observed: 0, gate: 0, unitIds: [] },
    ],
    measurements: [],
    timeline: [],
    startedAt: '2026-01-05T10:00:00.000Z',
    endedAt: '2026-01-05T10:02:30.500Z',
    evidenceDir: '/home/example/.cache/posthog-scenarios/6f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f',
}

type Captured = { [key: string]: unknown; properties: Record<string, unknown> }

type FakeProjectApi = {
    url: string
    captured: Captured[]
    queries: number
    hideForQueries: number
    close(): Promise<void>
}

function answer(response: ServerResponse, status: number, body: unknown): void {
    response.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body))
}

async function bodyOf(request: IncomingMessage): Promise<any> {
    const chunks: Buffer[] = []
    for await (const chunk of request) {
        chunks.push(chunk as Buffer)
    }
    try {
        return parseJSON(Buffer.concat(chunks).toString('utf8'))
    } catch {
        return undefined
    }
}

async function startFakeProjectApi(): Promise<FakeProjectApi> {
    const fake = { captured: [] as Captured[], queries: 0, hideForQueries: 0 }
    const server: Server = createServer((request, response) => {
        void (async () => {
            const body = await bodyOf(request)
            const json = request.headers['content-type'] === 'application/json'
            if (request.method === 'POST' && (request.url === '/i/v0/e/' || request.url === '/i/v0/e')) {
                const unknown = Object.keys(body ?? {}).filter((key) => !CAPTURE_KEYS.includes(key))
                if (!json || body?.api_key !== TOKEN) {
                    return answer(response, 401, { type: 'authentication_error' })
                }
                if (unknown.length > 0 || typeof body.event !== 'string' || typeof body.distinct_id !== 'string') {
                    return answer(response, 400, { type: 'validation_error', unknown })
                }
                if (typeof body.uuid !== 'string' || !UUID.test(body.uuid)) {
                    return answer(response, 400, { type: 'validation_error', attr: 'uuid' })
                }
                fake.captured.push(body)
                return answer(response, 200, { status: 'Ok' })
            }
            if (request.method === 'POST' && request.url === `/api/projects/${PROJECT_ID}/query/`) {
                if (request.headers.authorization !== `Bearer ${READ_KEY}`) {
                    return answer(response, 401, { type: 'authentication_error' })
                }
                const query = body?.query
                const placeholders = [...String(query?.query).matchAll(/\{(\w+)\}/g)].map(([, name]) => name)
                if (
                    !json ||
                    Object.keys(body).join() !== 'query' ||
                    query.kind !== 'HogQLQuery' ||
                    typeof query.query !== 'string' ||
                    Object.keys(query).some((key) => !['kind', 'query', 'values'].includes(key)) ||
                    placeholders.some((name) => query.values?.[name] === undefined)
                ) {
                    return answer(response, 400, { type: 'validation_error' })
                }
                fake.queries += 1
                const visible = fake.queries > fake.hideForQueries
                const rows = fake.captured
                    .filter((event) => visible && event.properties.run_id === query.values?.run_id)
                    .map(({ uuid }) => [uuid])
                return answer(response, 200, { columns: ['uuid'], results: rows })
            }
            return answer(response, 404, { type: 'invalid_request' })
        })()
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo
    return Object.assign(fake, {
        url: `http://127.0.0.1:${port}`,
        close: () => new Promise<void>((resolve) => server.close(() => resolve())),
    })
}

function git(cwd: string, ...args: string[]): string {
    return execFileSync('git', ['-c', 'user.name=Example', '-c', 'user.email=runner@example.com', ...args], {
        cwd,
        encoding: 'utf8',
    }).trim()
}

describe('scorecard', () => {
    let api: FakeProjectApi
    let env: NodeJS.ProcessEnv

    beforeEach(async () => {
        api = await startFakeProjectApi()
        env = {
            SCENARIO_RUNS_HOST: `${api.url}/`,
            SCENARIO_RUNS_PROJECT_ID: PROJECT_ID,
            SCENARIO_RUNS_PROJECT_TOKEN: TOKEN,
            SCENARIO_RUNS_READ_KEY: READ_KEY,
        }
    })

    afterEach(async () => {
        await api.close()
    })

    it('captures one scorecard event with the flattened schema v1 properties and reads it back', async () => {
        api.hideForQueries = 2

        const outcome = await publish(scorecardOf(RESULT, SMOKE, PROVENANCE), env, { pollMs: 5, deadlineMs: 5000 })

        expect(outcome).toEqual({ recorded: true })
        expect(exitCodeOf({ status: RESULT.status, scorecardError: outcome.problem })).toBe(1)
        expect(api.captured).toEqual([
            {
                api_key: TOKEN,
                event: 'scorecard',
                distinct_id: 'scenario-runner',
                uuid: RUN_ID,
                timestamp: '2026-01-05T10:02:30.500Z',
                properties: {
                    schema_version: 1,
                    run_id: RUN_ID,
                    card_id: 'smoke',
                    card_version: 1,
                    card_hash: SMOKE.cardHash,
                    profile_name: 'synthetic',
                    profile_hash: SMOKE.profileHash,
                    head_sha: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00',
                    head_dirty: true,
                    origin: 'local-agent',
                    target: 'local',
                    fingerprint: expect.stringMatching(/^[0-9a-f]{64}$/),
                    host_cpu: 'Example CPU 3000 x 8',
                    host_memory_gb: 32,
                    runner_version: '1111111111111111111111111111111111111111',
                    generator_version: '2222222222222222222222222222222222222222',
                    valves_version: '4b825dc642cb6eb9a060e54bf8d69288fbee4904',
                    seed: 1,
                    status: 'failed',
                    status_reason: 'at_least_once failed: run-x-3 email: the edge never received it',
                    started_at: '2026-01-05T10:00:00.000Z',
                    ended_at: '2026-01-05T10:02:30.500Z',
                    duration_s: 150.5,
                    units_target: 60,
                    units_offered: 58,
                    converged: true,
                    unfinished_jobs: 0,
                    inv_at_least_once_passed: false,
                    inv_at_least_once_observed: 2,
                    inv_at_least_once_gate: null,
                    inv_at_least_once_violation: 'run-x-3 email: the edge never received it',
                    inv_at_least_once_ids: ['run-x-3', 'run-x-7'],
                    inv_duplicate_sends_passed: true,
                    inv_duplicate_sends_observed: 0,
                    inv_duplicate_sends_gate: 0,
                    inv_duplicate_sends_violation: null,
                    inv_duplicate_sends_ids: [],
                    invariants_failed: ['at_least_once'],
                    valve_timeline: [],
                    evidence_dir: RESULT.evidenceDir,
                },
            },
        ])
    })

    it('reports a run that stopped before the drive with empty verdict fields', () => {
        const stopped: RunResult = {
            ...RESULT,
            units: undefined,
            convergence: undefined,
            invariants: [],
        }

        expect(scorecardOf(stopped, SMOKE, PROVENANCE)).toMatchObject({
            units_target: null,
            units_offered: null,
            converged: null,
            unfinished_jobs: null,
            invariants_failed: [],
        })
    })

    it('gives up with exit 3 when the readback never returns the event', async () => {
        api.hideForQueries = Infinity

        const outcome = await publish(scorecardOf(RESULT, SMOKE, PROVENANCE), env, { pollMs: 5, deadlineMs: 60 })

        expect(outcome).toEqual({
            recorded: false,
            problem: 'the scorecard was not read back within 0.06s: the query did not return the event yet',
        })
        expect(exitCodeOf({ status: 'passed', scorecardError: outcome.problem })).toBe(3)
        expect(api.captured).toHaveLength(1)
    })

    it.each<[string, string[], { recorded: boolean; problem?: string }]>([
        ['no credentials: nothing is written and the exit follows the status', [], { recorded: false }],
        [
            'some credentials: a configuration problem, and nothing is written',
            ['SCENARIO_RUNS_HOST', 'SCENARIO_RUNS_PROJECT_TOKEN'],
            {
                recorded: false,
                problem:
                    'Scorecard credentials are set only in part; set all of them or none. Missing: SCENARIO_RUNS_PROJECT_ID, SCENARIO_RUNS_READ_KEY',
            },
        ],
    ])('%s', async (_story, kept, expected) => {
        const partial = Object.fromEntries(Object.entries(env).filter(([name]) => kept.includes(name)))

        const outcome = await publish(scorecardOf(RESULT, SMOKE, PROVENANCE), partial, { pollMs: 5, deadlineMs: 60 })

        expect(outcome).toEqual(expected)
        expect(api.captured).toEqual([])
        expect(api.queries).toBe(0)
    })

    it.each<[string, boolean, (provenance: Provenance, loaded: LoadedCard) => [Provenance, LoadedCard]]>([
        ['the host CPU', true, (p, l) => [{ ...p, hostCpu: 'Example CPU 4000 x 16' }, l]],
        ['the host memory', true, (p, l) => [{ ...p, hostMemoryGb: 64 }, l]],
        ['the runner version', true, (p, l) => [{ ...p, runnerVersion: '3'.repeat(40) }, l]],
        ['the generator version', true, (p, l) => [{ ...p, generatorVersion: '3'.repeat(40) }, l]],
        ['the valves version', true, (p, l) => [{ ...p, valvesVersion: '3'.repeat(40) }, l]],
        ['the seed', true, (p, l) => [p, { ...l, card: { ...l.card, seed: 2 } }]],
        ['the head commit', false, (p, l) => [{ ...p, headSha: 'd'.repeat(40), headDirty: false }, l]],
    ])('a change to %s changes the fingerprint: %s', (_input, changes, change) => {
        const [provenance, loaded] = change(PROVENANCE, SMOKE)

        const before = scorecardOf(RESULT, SMOKE, PROVENANCE).fingerprint
        const after = scorecardOf(RESULT, loaded, provenance).fingerprint

        expect(after !== before).toBe(changes)
    })

    describe('provenance', () => {
        let repo: string
        let scenarios: string

        beforeEach(() => {
            repo = mkdtempSync(path.join(os.tmpdir(), 'scenario-provenance-'))
            scenarios = path.join(repo, 'nodejs', 'tests', 'scenarios')
            for (const file of [
                'nodejs/tests/scenarios/generator/traffic.ts',
                'nodejs/tests/scenarios/judge/judge.ts',
                'nodejs/tests/scenarios/main.ts',
                'nodejs/src/service.ts',
                'rust/Cargo.lock',
            ]) {
                mkdirSync(path.dirname(path.join(repo, file)), { recursive: true })
                writeFileSync(path.join(repo, file), `${file}\n`)
            }
            git(repo, 'init', '-q')
            git(repo, 'add', '.')
            git(repo, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'fixture')
        })

        afterEach(() => {
            rmSync(repo, { recursive: true, force: true })
        })

        it('versions each part of the runner by its git tree', () => {
            const listing = git(repo, 'ls-tree', 'HEAD:nodejs/tests/scenarios')
                .split('\n')
                .filter((line) => !line.endsWith('\tgenerator'))
                .join('\n')
            const runnerTree = execFileSync('git', ['mktree'], { cwd: repo, input: `${listing}\n`, encoding: 'utf8' })

            expect(provenanceOf(scenarios)).toMatchObject({
                headSha: git(repo, 'rev-parse', 'HEAD'),
                headDirty: false,
                runnerVersion: runnerTree.trim(),
                generatorVersion: git(repo, 'rev-parse', 'HEAD:nodejs/tests/scenarios/generator'),
                valvesVersion: git(repo, 'hash-object', '-t', 'tree', '/dev/null'),
            })
        })

        it.each([
            ['an edit to the generator', 'nodejs/tests/scenarios/generator/traffic.ts', true],
            ['a new file in the package', 'nodejs/src/added.ts', true],
            ['an edit outside the package', 'rust/Cargo.lock', false],
        ])('%s sets head_dirty: %s', (_story, file, dirty) => {
            writeFileSync(path.join(repo, file), 'edited\n')

            expect(provenanceOf(scenarios).headDirty).toBe(dirty)
        })
    })
})
