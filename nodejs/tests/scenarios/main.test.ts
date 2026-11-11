import path from 'path'

import { load } from './cards'
import { main, runCards } from './main'
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
    beforeEach(() => {
        jest.spyOn(process.stdout, 'write').mockReturnValue(true)
        jest.spyOn(process.stderr, 'write').mockReturnValue(true)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each<[string, 'up' | 'first run' | 'never', number]>([
        ['every card ran and passed', 'never', EXIT_CODE.passed],
        ['an interrupt during up skipped every card', 'up', EXIT_CODE.invalid],
        ['an interrupt after the first card skipped the second', 'first run', EXIT_CODE.invalid],
    ])('exits with the right code when %s', async (_story, interruptAt, code) => {
        const interrupt = new AbortController()
        const runner: Runner = {
            up: () => Promise.resolve(interruptAt === 'up' ? interrupt.abort() : undefined),
            run: (loaded) => {
                if (interruptAt === 'first run') {
                    interrupt.abort()
                }
                return Promise.resolve(passed(loaded.card.id))
            },
            down: () => Promise.resolve(),
        }

        expect(await runCards(runner, [SMOKE, SMOKE], interrupt.signal)).toBe(code)
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
        const code = await main(['run', 'smoke'], {
            SCENARIO_RUNS_HOST: 'http://127.0.0.1:1',
            SCENARIO_RUNS_PROJECT_TOKEN: 'phc_fake_token',
        })

        expect(code).toBe(EXIT_CODE.invalid)
        expect(jest.mocked(process.stderr.write)).toHaveBeenCalledWith(
            expect.stringContaining('Missing: SCENARIO_RUNS_PROJECT_ID, SCENARIO_RUNS_READ_KEY')
        )
    })
})
