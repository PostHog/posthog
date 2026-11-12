import { mkdtempSync, rmSync } from 'fs'
import os from 'os'
import path from 'path'

import { load } from './cards'
import { Environment } from './environment/environment'
import { runCards } from './main'
import { RunResult, Runner, createRunner } from './runner/runner'
import { EXIT_CODE } from './runner/status'

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

describe('runCards', () => {
    let stderr: jest.SpyInstance

    beforeEach(() => {
        jest.spyOn(process.stdout, 'write').mockReturnValue(true)
        stderr = jest.spyOn(process.stderr, 'write').mockReturnValue(true)
    })

    afterEach(() => {
        jest.restoreAllMocks()
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

    it('names the failed reset for the cards it skips once a reset stopped the environment', async () => {
        const cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-main-'))
        let edgeUrl: string | undefined = 'http://127.0.0.1:1'
        const environment: Environment = {
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
            role: (name) => ({ name, metricsUrl: '' }),
            dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
            exits: () => [],
            down: () => Promise.resolve(),
        }
        const runner = createRunner(environment, { ...process.env, XDG_CACHE_HOME: cacheHome })

        try {
            const exitCode = await runCards(runner, [SMOKE, SMOKE], new AbortController().signal)

            expect({ exitCode, stderr: stderr.mock.calls.map(([text]) => text).join('') }).toEqual({
                exitCode: EXIT_CODE.invalid,
                stderr: expect.stringMatching(
                    /The reset before run [\w-]+ failed and stopped the environment: cdp-api did not join its consumer group\. Restart the runner, then run the card again\.\nSkipped 1 of 2 cards after the error\.\n$/
                ),
            })
        } finally {
            rmSync(cacheHome, { recursive: true, force: true })
        }
    })
})
