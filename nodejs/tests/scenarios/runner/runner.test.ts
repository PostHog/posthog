import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { LoadedCard, load } from '../cards'
import { Environment } from '../environment/environment'
import { createRunner } from './runner'

const SMOKE = load(path.join(__dirname, '..', 'cards', 'smoke.yaml'))
const PROCESS_DATABASE_URL = 'postgres://scenario:scenario@127.0.0.1:2/scenario'
const PROFILE_DATABASE_URL = 'postgres://scenario:scenario@127.0.0.1:1/scenario'
const NEVER_ABORTED = new AbortController().signal

const withSettings = (settings: Record<string, string>): LoadedCard => ({
    ...SMOKE,
    profile: { ...SMOKE.profile, settings },
})

describe('runner', () => {
    let cacheHome: string
    let stateDir: string
    let duringReset: () => void

    const environment: Environment = {
        up: () => Promise.resolve(),
        reset: () => Promise.resolve(duringReset()),
        role: (name) => ({ name, metricsUrl: '' }),
        health: () => Promise.resolve({ healthy: true, down: [] }),
        exits: () => [],
        down: () => Promise.resolve(),
    }

    const runner = () =>
        createRunner(environment, { ...process.env, XDG_CACHE_HOME: cacheHome, DATABASE_URL: PROCESS_DATABASE_URL })

    beforeEach(() => {
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-runner-'))
        stateDir = path.join(cacheHome, 'posthog-scenarios')
        duringReset = () => undefined
    })

    afterEach(() => {
        rmSync(cacheHome, { recursive: true, force: true })
    })

    it.each<[string, () => void, LoadedCard, RegExp]>([
        [
            'seeds through the database the profile names',
            () => undefined,
            withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }),
            /^the run stopped: .*127\.0\.0\.1:1\b/,
        ],
        [
            'keeps the result when its evidence cannot be written',
            () => writeFileSync(stateDir, 'not a directory'),
            withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }),
            /; the evidence could not be written: .*ENOTDIR/,
        ],
    ])('%s', async (_story, arrange, loaded, statusReason) => {
        arrange()

        const result = await runner().run(loaded, NEVER_ABORTED)

        expect(result).toMatchObject({ status: 'invalid', statusReason: expect.stringMatching(statusReason) })
    })

    it("keeps only this run's part of each role log", async () => {
        mkdirSync(stateDir, { recursive: true })
        const log = path.join(stateDir, 'cdp-api.log')
        writeFileSync(log, 'line from an earlier run\n')
        duringReset = () => appendFileSync(log, 'line from this run\n')

        const { evidenceDir } = await runner().run(withSettings({}), NEVER_ABORTED)

        expect(readFileSync(path.join(evidenceDir, 'logs', 'cdp-api.log'), 'utf8')).toBe('line from this run\n')
    })
})
