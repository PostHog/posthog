import { randomUUID } from 'crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import { Server, createServer } from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'
import { parse, stringify } from 'yaml'

import { parseJSON } from '~/common/utils/json-parse'

import { PROFILES_DIR, load, loadText } from './cards'
import { Environment } from './environment/environment'
import * as processes from './environment/processes'
import * as stack from './environment/stack'
import { main, runCards } from './main'
import * as evidenceFile from './runner/evidence-file'
import { controlOf } from './runner/pair'
import { RunResult, Runner, createRunner } from './runner/runner'
import { EXIT_CODE } from './runner/status'
import { startFakeProjectApi } from './scorecard/fake-project-api'
import { STORE_URL } from './store/client'
import { TestStore, UNREACHABLE_STORE, startTestStore, storeEnvOf } from './store/test-store'

const SMOKE = load(path.join(__dirname, 'cards', 'smoke.yaml'))
const DESTINATION_ERRORS = parse(readFileSync(path.join(__dirname, 'cards', 'destination-errors.yaml'), 'utf8'))
const PAIRABLE = loadText('pairable', {
    card: stringify({ ...DESTINATION_ERRORS, invariants: [...DESTINATION_ERRORS.invariants, { name: 'no_loss' }] }),
    profile: readFileSync(path.join(PROFILES_DIR, `${DESTINATION_ERRORS.profile}.yaml`), 'utf8'),
})

const passed = (cardId: string): RunResult => ({
    runId: 'run-a',
    status: 'passed',
    statusReason: 'every invariant held',
    recorded: false,
    cardId,
    cardHash: 'card-hash',
    profileHash: 'profile-hash',
    origin: 'local-agent',
    target: 'local',
    bars: [],
    invariants: [],
    measurements: [],
    admissions: [],
    timeline: [],
    startedAt: '2026-01-01T00:00:00.000Z',
    endedAt: '2026-01-01T00:00:01.000Z',
    evidenceDir: '/tmp/scenario-evidence',
})

const runnerEnv = (cacheHome: string, credentials: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv => ({
    ...Object.fromEntries(
        Object.entries(process.env).filter(([name]) => !name.startsWith('SCENARIO_RUNS_') && name !== STORE_URL)
    ),
    XDG_CACHE_HOME: cacheHome,
    ...credentials,
})

function fakeEnvironment({ resetFails = true } = {}): Environment {
    let edgeUrl: string | undefined = 'http://127.0.0.1:1'
    return {
        up: () => Promise.resolve(),
        reset: () => {
            if (!resetFails) {
                return Promise.resolve()
            }
            edgeUrl = undefined
            return Promise.reject(new Error('cdp-api did not join its consumer group'))
        },
        edgeUrl: () => {
            if (edgeUrl === undefined) {
                throw new Error('Start the environment with up() before edgeUrl().')
            }
            return edgeUrl
        },
        role: (name) => ({ name, replica: 0, url: '', metricsUrl: '' }),
        roles: () => [],
        dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
        actuate: () => Promise.reject(new Error('the main test schedules no valves')),
        writerCpu: () => Promise.reject(new Error('these runs read no writer CPU')),
        wiring: () => Promise.reject(new Error('the reset fails before the wiring is read')),
        exits: () => [],
        groupLag: () => Promise.resolve(0),
        down: () => Promise.resolve(),
    }
}

describe('runCards', () => {
    let stderr: jest.SpyInstance
    let cacheHome: string

    beforeEach(() => {
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-main-'))
        jest.spyOn(process.stdout, 'write').mockReturnValue(true)
        stderr = jest.spyOn(process.stderr, 'write').mockReturnValue(true)
    })

    afterEach(() => {
        jest.restoreAllMocks()
        rmSync(cacheHome, { recursive: true, force: true })
    })

    it.each<[string, 'up' | 'first run' | 'up fails' | 'never', number, string]>([
        ['every card ran and passed', 'never', EXIT_CODE.passed, ''],
        [
            'an interrupt during up skipped every card',
            'up',
            EXIT_CODE.invalid,
            'Interrupted before 2 of 2 cards ran.\n',
        ],
        [
            'an interrupt after the first card skipped the second',
            'first run',
            EXIT_CODE.invalid,
            'Interrupted before 1 of 2 cards ran.\n',
        ],
        [
            'up failed before any card ran',
            'up fails',
            EXIT_CODE.invalid,
            'the stack is held by another run\nSkipped 2 of 2 cards after the error.\n',
        ],
    ])('exits with the right code and says why cards were skipped when %s', async (_story, stopAt, code, said) => {
        const interrupt = new AbortController()
        const runner: Runner = {
            up: () => {
                if (stopAt === 'up fails') {
                    return Promise.reject(new Error('the stack is held by another run'))
                }
                return Promise.resolve(stopAt === 'up' ? interrupt.abort() : undefined)
            },
            run: (loaded) => {
                if (stopAt === 'first run') {
                    interrupt.abort()
                }
                return Promise.resolve(passed(loaded.card.id))
            },
            runPair: () => Promise.reject(new Error('these runs pair no card')),
            down: () => Promise.resolve(),
        }

        const exitCode = await runCards(runner, [SMOKE, SMOKE], interrupt.signal)

        expect({ exitCode, stderr: stderr.mock.calls.map(([text]) => text).join('') }).toEqual({
            exitCode: code,
            stderr: said,
        })
    })

    it.each<[string, Partial<RunResult>, string[]]>([
        [
            'the scorecard write failed',
            { scorecardError: 'capture answered 503' },
            ['smoke: passed, every invariant held\n', 'scorecard: capture answered 503\n'],
        ],
        [
            'both the evidence and the scorecard write failed',
            {
                status: 'invalid',
                statusReason: 'every invariant held; the evidence could not be written: ENOSPC',
                scorecardError: 'capture answered 503',
            },
            [
                'smoke: invalid, every invariant held; the evidence could not be written: ENOSPC\n',
                'scorecard: capture answered 503\n',
            ],
        ],
    ])('exits 3 and prints every error when %s', async (_story, outcome, printed) => {
        const runner: Runner = {
            up: () => Promise.resolve(),
            run: (loaded) => Promise.resolve({ ...passed(loaded.card.id), ...outcome }),
            runPair: () => Promise.reject(new Error('these runs pair no card')),
            down: () => Promise.resolve(),
        }

        expect(await runCards(runner, [SMOKE], new AbortController().signal)).toBe(EXIT_CODE.writeFailed)
        const stdout = jest.mocked(process.stdout.write).mock.calls.map(([text]) => text)
        expect(stdout).toEqual(expect.arrayContaining(printed))
    })

    it('prints a failed store report and keeps the exit code of the run', async () => {
        const runner: Runner = {
            up: () => Promise.resolve(),
            run: (loaded) =>
                Promise.resolve({
                    ...passed(loaded.card.id),
                    recorded: true,
                    storeError: 'the run store answered 503',
                }),
            runPair: () => Promise.reject(new Error('these runs pair no card')),
            down: () => Promise.resolve(),
        }

        expect(await runCards(runner, [SMOKE], new AbortController().signal)).toBe(EXIT_CODE.passed)
        const stdout = jest.mocked(process.stdout.write).mock.calls.map(([text]) => text)
        expect(stdout).toContain('store: the run store answered 503\n')
    })

    it('refuses partial scorecard credentials before it starts the stack', async () => {
        jest.spyOn(processes, 'terminate').mockRejectedValue(new Error('The preflight test reached process cleanup.'))
        jest.spyOn(stack, 'startStack').mockRejectedValue(new Error('The preflight test reached the dev stack.'))

        const code = await main(['run', 'smoke'], {
            SCENARIO_RUNS_HOST: 'http://127.0.0.1:1',
            SCENARIO_RUNS_PROJECT_TOKEN: 'phc_fake_token',
        })

        expect(code).toBe(EXIT_CODE.invalid)
        expect(jest.mocked(process.stderr.write)).toHaveBeenCalledWith(
            expect.stringContaining('Missing: SCENARIO_RUNS_PROJECT_ID, SCENARIO_RUNS_READ_KEY')
        )
        const stderr = jest.mocked(process.stderr.write).mock.calls.map(([text]) => String(text))
        expect(stderr.filter((text) => text.includes('The preflight test reached'))).toEqual([])
    })

    it.each<[string, string[], NodeJS.ProcessEnv, RegExp]>([
        [
            'a card without valves',
            ['run', 'smoke', '--pair'],
            {},
            /^smoke: --pair needs a card that applies valves and judges no_loss/,
        ],
        [
            'a card that judges no no_loss',
            ['run', 'destination-errors', '--pair'],
            {},
            /^destination-errors: --pair needs a card that applies valves and judges no_loss/,
        ],
        [
            'the dev target',
            ['run', 'dev-smoke', '--target', 'dev', '--pair'],
            {},
            /^--pair runs on the local target only/,
        ],
        [
            'a run host',
            ['run', 'smoke', '--pair'],
            { SCENARIO_RUN_MANIFEST: '/nonexistent/manifest.json' },
            /^--pair runs on the local target only/,
        ],
    ])('refuses --pair for %s before it starts the stack', async (_story, argv, env, refusal) => {
        jest.spyOn(processes, 'terminate').mockRejectedValue(new Error('The preflight test reached process cleanup.'))
        jest.spyOn(stack, 'startStack').mockRejectedValue(new Error('The preflight test reached the dev stack.'))

        expect(await main(argv, env)).toBe(EXIT_CODE.invalid)

        const stderr = jest.mocked(process.stderr.write).mock.calls.map(([text]) => String(text))
        expect(stderr.join('')).toMatch(refusal)
        expect(stack.startStack).not.toHaveBeenCalled()
    })

    it('names the failed reset for the cards it skips once a reset stopped the environment', async () => {
        const runner = createRunner(fakeEnvironment(), runnerEnv(cacheHome))

        const exitCode = await runCards(runner, [SMOKE, SMOKE], new AbortController().signal)

        expect({ exitCode, stderr: stderr.mock.calls.map(([text]) => text).join('') }).toEqual({
            exitCode: EXIT_CODE.invalid,
            stderr: expect.stringMatching(
                /The reset before run [\w-]+ failed and stopped the environment: cdp-api did not join its consumer group\. Restart the runner, then run the card again\.\nSkipped 1 of 2 cards after the error\.\n$/
            ),
        })
    })

    it('saves both scorecards of a paired card, then publishes each with the pair', async () => {
        const api = await startFakeProjectApi()
        const unseedable = { ...api.credentials, DATABASE_URL: 'postgres://scenario:scenario@127.0.0.1:1/scenario' }
        const runner = createRunner(fakeEnvironment({ resetFails: false }), runnerEnv(cacheHome, unseedable))
        const stateDir = path.join(cacheHome, 'posthog-scenarios')
        const savedAtCapture: number[] = []
        api.onCapture = () =>
            savedAtCapture.push(
                readdirSync(stateDir).filter((run) => existsSync(path.join(stateDir, run, 'scorecard.json'))).length
            )

        try {
            const exitCode = await runCards(runner, [PAIRABLE], new AbortController().signal, { pair: true })

            const [control, faulted] = api.captured.map(({ properties }) => properties)
            const pair = {
                pair_attribution: 'unjudged',
                pair_reason: expect.stringMatching(/^the control run is invalid: /),
                pair_control_run_id: control.run_id,
                pair_faulted_run_id: faulted.run_id,
            }
            expect({ exitCode, captured: api.captured.length, control, faulted }).toEqual({
                exitCode: EXIT_CODE.invalid,
                captured: 2,
                control: expect.objectContaining({ ...pair, pair_role: 'control', card_id: 'destination-errors' }),
                faulted: expect.objectContaining({ ...pair, pair_role: 'faulted', card_id: 'destination-errors' }),
            })
            expect(control.run_id).not.toEqual(faulted.run_id)
            expect([control.card_hash, faulted.card_hash]).toEqual([controlOf(PAIRABLE).cardHash, PAIRABLE.cardHash])
            expect(savedAtCapture).toEqual([2, 2])
        } finally {
            await api.close()
        }
    })

    it('reads the pair again when a saved scorecard cannot be written, and saves the other run with it before publishing', async () => {
        const api = await startFakeProjectApi()
        const unseedable = { ...api.credentials, DATABASE_URL: 'postgres://scenario:scenario@127.0.0.1:1/scenario' }
        const runner = createRunner(fakeEnvironment({ resetFails: false }), runnerEnv(cacheHome, unseedable))
        const { writeJson } = jest.requireActual<typeof evidenceFile>('./runner/evidence-file')
        let failed = false
        jest.spyOn(evidenceFile, 'writeJson').mockImplementation((dir, name, value) => {
            if (name === 'scorecard.json' && !failed) {
                failed = true
                throw new Error('disk full')
            }
            writeJson(dir, name, value)
        })

        let savedAtFirstCapture: { event: { pair_reason: unknown } } | undefined
        api.onCapture = ({ properties }) => {
            savedAtFirstCapture ??= parseJSON(
                readFileSync(
                    path.join(cacheHome, 'posthog-scenarios', String(properties.pair_faulted_run_id), 'scorecard.json'),
                    'utf8'
                )
            )
        }

        try {
            await runCards(runner, [PAIRABLE], new AbortController().signal, { pair: true })

            const [control, faulted] = api.captured.map(({ properties }) => properties)
            const reason = expect.stringMatching(
                /^the control run is invalid: .*; the evidence could not be written: disk full$/
            )
            expect([control.pair_reason, faulted.pair_reason, savedAtFirstCapture?.event.pair_reason]).toEqual([
                reason,
                reason,
                reason,
            ])
        } finally {
            await api.close()
        }
    })

    it('says the scorecard was captured when the run is interrupted before it was read back', async () => {
        const api = await startFakeProjectApi()
        const interrupt = new AbortController()
        api.hideForQueries = Infinity
        api.onCapture = () => interrupt.abort()
        const runner = createRunner(fakeEnvironment(), runnerEnv(cacheHome, api.credentials))

        try {
            const exitCode = await runCards(runner, [SMOKE], interrupt.signal)

            const stdout = jest.mocked(process.stdout.write).mock.calls.map(([text]) => String(text))
            expect({ exitCode, scorecard: stdout.filter((text) => text.startsWith('scorecard:')) }).toEqual({
                exitCode: EXIT_CODE.invalid,
                scorecard: ['scorecard: captured; the run was interrupted before it was read back\n'],
            })
            expect(api.captured).toHaveLength(1)
        } finally {
            await api.close()
        }
    })
})

describe('publish', () => {
    let store: TestStore
    let cacheHome: string
    let stdout: jest.SpyInstance
    let stderr: jest.SpyInstance

    const runDirOf = (runId: string): string => path.join(cacheHome, 'posthog-scenarios', runId)

    const saveRun = (runId: string, saved: Record<string, unknown>): void => {
        mkdirSync(runDirOf(runId), { recursive: true })
        writeFileSync(path.join(runDirOf(runId), 'scorecard.json'), JSON.stringify({ runId, ...saved }))
    }

    const eventOf = (runId: string): Record<string, unknown> => ({
        schema_version: 1,
        run_id: runId,
        card_id: 'smoke',
        status: 'passed',
        status_reason: 'every invariant held',
        started_at: '2026-01-01T00:00:00.000Z',
        ended_at: '2026-01-01T00:00:01.000Z',
        evidence_dir: '/tmp/scenario-evidence',
    })

    const printed = (spy: jest.SpyInstance): string => spy.mock.calls.map(([text]) => text).join('')

    let errorPage: Server

    beforeAll(async () => {
        store = await startTestStore('publish')
        errorPage = createServer((request, response) =>
            response.writeHead(502).end('x'.repeat(request.url?.startsWith('/huge/') ? 100_000 : 5000))
        )
        await new Promise<void>((resolve) => errorPage.listen(0, '127.0.0.1', resolve))
    })

    afterAll(async () => {
        await store.close()
        await new Promise((resolve) => errorPage.close(resolve))
    })

    beforeEach(() => {
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-publish-'))
        stdout = jest.spyOn(process.stdout, 'write').mockReturnValue(true)
        stderr = jest.spyOn(process.stderr, 'write').mockReturnValue(true)
    })

    afterEach(() => {
        jest.restoreAllMocks()
        rmSync(cacheHome, { recursive: true, force: true })
    })

    it('stores a run saved before runs named their adapters as a Workflows run, by id, by path or by a relative path', async () => {
        const [byId, byPath, byRelativePath] = [randomUUID(), randomUUID(), randomUUID()]
        saveRun(byId, { host: 'box-that-ran-it', event: eventOf(byId) })
        saveRun(byPath, { event: eventOf(byPath) })
        mkdirSync(path.join(cacheHome, byRelativePath))
        writeFileSync(
            path.join(cacheHome, byRelativePath, 'scorecard.json'),
            JSON.stringify({ event: eventOf(byRelativePath) })
        )
        const cwd = process.cwd()
        process.chdir(cacheHome)

        const exitCode = await main(['publish', byId, runDirOf(byPath), byRelativePath], {
            XDG_CACHE_HOME: cacheHome,
            ...store.envOf(cacheHome),
        }).finally(() => process.chdir(cwd))

        expect(exitCode).toBe(EXIT_CODE.passed)
        expect(await store.read(byId)).toMatchObject({ adapters: ['workflows'], owners: [], host: 'box-that-ran-it' })
        expect(await store.read(byPath)).toMatchObject({ scorecard: { ...eventOf(byPath), adapters: ['workflows'] } })
        expect(await store.read(byRelativePath)).toMatchObject({ runId: byRelativePath })
        expect(printed(stdout)).toBe(`${byId}: stored\n${byPath}: stored\n${byRelativePath}: stored\n`)
    })

    it('skips run directories without a scorecard under --all, and fails on one named outright', async () => {
        const [saved, unsaved] = [randomUUID(), randomUUID()]
        saveRun(saved, { event: eventOf(saved) })
        mkdirSync(runDirOf(unsaved), { recursive: true })
        mkdirSync(path.join(cacheHome, 'posthog-scenarios', 'logs'))
        const env = { XDG_CACHE_HOME: cacheHome, ...store.envOf(cacheHome) }

        expect(await main(['publish', '--all'], env)).toBe(EXIT_CODE.passed)
        expect(printed(stdout)).toBe(`${saved}: stored\n`)

        const eventless = randomUUID()
        saveRun(eventless, { status: 'passed' })

        expect(await main(['publish', unsaved, eventless], env)).toBe(EXIT_CODE.writeFailed)
        expect(printed(stderr)).toContain(
            `${unsaved}: no scorecard at ${path.join(runDirOf(unsaved), 'scorecard.json')}`
        )
        expect(printed(stderr)).toContain(
            `${eventless}: ${path.join(runDirOf(eventless), 'scorecard.json')} holds no scorecard event`
        )
        expect(await store.read(unsaved)).toBeUndefined()
    })

    it.each([
        ['publish', ['publish', '--all', '--target', 'dev']],
        ['seed-backlog', ['seed-backlog', '--profile', 'profiles/dev.yaml', '--target', 'dev']],
    ])('refuses --target on %s, which only run reads', async (_command, argv) => {
        expect(await main(argv, { XDG_CACHE_HOME: cacheHome, [STORE_URL]: UNREACHABLE_STORE })).toBe(EXIT_CODE.invalid)

        expect(printed(stderr)).toMatch(/^Usage: /)
    })

    it.each<[string, (home: string) => NodeJS.ProcessEnv, number, RegExp]>([
        ['no run store is set', (home) => ({ HOME: home }), EXIT_CODE.invalid, /Set SCENARIO_STORE_URL/],
        [
            'the run token file is missing',
            (home) => ({ HOME: home, [STORE_URL]: UNREACHABLE_STORE }),
            EXIT_CODE.writeFailed,
            /holds no run token/,
        ],
        [
            'the run store answers with a long error page',
            (home) => storeEnvOf(home, `http://127.0.0.1:${(errorPage.address() as AddressInfo).port}`),
            EXIT_CODE.writeFailed,
            /the run store answered 502: x{200}\n$/,
        ],
        [
            'the run store answers with an error page past the response cap',
            (home) => storeEnvOf(home, `http://127.0.0.1:${(errorPage.address() as AddressInfo).port}/huge`),
            EXIT_CODE.writeFailed,
            /the run store answered 502: Response body is larger than the 65536 byte limit\n$/,
        ],
        [
            'the run store is down',
            (home) => storeEnvOf(home, UNREACHABLE_STORE),
            EXIT_CODE.writeFailed,
            /the run store did not answer/,
        ],
    ])('stores nothing and says why when %s', async (_story, envOf, code, said) => {
        const runId = randomUUID()
        saveRun(runId, { event: eventOf(runId) })

        expect(await main(['publish', runId], { XDG_CACHE_HOME: cacheHome, ...envOf(cacheHome) })).toBe(code)

        expect(printed(stderr)).toMatch(said)
        expect(await store.read(runId)).toBeUndefined()
    })
})
