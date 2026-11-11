import path from 'path'

import { load } from './cards'
import { runCards } from './main'
import { RunResult, Runner } from './runner/runner'
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
})
