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
})
