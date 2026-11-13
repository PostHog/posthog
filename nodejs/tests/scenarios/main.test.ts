import { mkdtempSync, rmSync } from 'fs'
import os from 'os'
import path from 'path'

import { load } from './cards'
import { Environment } from './environment/environment'
import * as processes from './environment/processes'
import * as stack from './environment/stack'
import { main, runCards } from './main'
import { RunResult, Runner, createRunner } from './runner/runner'
import { EXIT_CODE } from './runner/status'
import { startFakeProjectApi } from './scorecard/fake-project-api'

const SMOKE = load(path.join(__dirname, 'cards', 'smoke.yaml'))

const passed = (cardId: string): RunResult => ({
    runId: 'run-a',
    status: 'passed',
    statusReason: 'every invariant held',
    recorded: false,
    cardId,
    cardHash: 'card-hash',
    profileHash: 'profile-hash',
    origin: 'local-agent',
    invariants: [],
    measurements: [],
    timeline: [],
    startedAt: '2026-01-01T00:00:00.000Z',
    endedAt: '2026-01-01T00:00:01.000Z',
    evidenceDir: '/tmp/scenario-evidence',
})

const runnerEnv = (cacheHome: string, credentials: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv => ({
    ...Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith('SCENARIO_RUNS_'))),
    XDG_CACHE_HOME: cacheHome,
    ...credentials,
})

function environmentWhoseResetFails(): Environment {
    let edgeUrl: string | undefined = 'http://127.0.0.1:1'
    return {
        up: () => Promise.resolve(),
        reset: () => {
            edgeUrl = undefined
            return Promise.reject(new Error('cdp-api did not join its consumer group'))
        },
        edgeUrl: () => {
            if (edgeUrl === undefined) {
                throw new Error('Start the environment with up() before edgeUrl().')
            }
            return edgeUrl
        },
        role: (name) => ({ name, url: '', metricsUrl: '' }),
        dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
        actuate: () => Promise.reject(new Error('the main test schedules no valves')),
        exits: () => [],
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
            down: () => Promise.resolve(),
        }

        expect(await runCards(runner, [SMOKE], new AbortController().signal)).toBe(EXIT_CODE.writeFailed)
        const stdout = jest.mocked(process.stdout.write).mock.calls.map(([text]) => text)
        expect(stdout).toEqual(expect.arrayContaining(printed))
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

    it('names the failed reset for the cards it skips once a reset stopped the environment', async () => {
        const runner = createRunner(environmentWhoseResetFails(), runnerEnv(cacheHome))

        const exitCode = await runCards(runner, [SMOKE, SMOKE], new AbortController().signal)

        expect({ exitCode, stderr: stderr.mock.calls.map(([text]) => text).join('') }).toEqual({
            exitCode: EXIT_CODE.invalid,
            stderr: expect.stringMatching(
                /The reset before run [\w-]+ failed and stopped the environment: cdp-api did not join its consumer group\. Restart the runner, then run the card again\.\nSkipped 1 of 2 cards after the error\.\n$/
            ),
        })
    })

    it('says the scorecard was captured when the run is interrupted before it was read back', async () => {
        const api = await startFakeProjectApi()
        const interrupt = new AbortController()
        api.hideForQueries = Infinity
        api.onCapture = () => interrupt.abort()
        const runner = createRunner(environmentWhoseResetFails(), runnerEnv(cacheHome, api.credentials))

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
