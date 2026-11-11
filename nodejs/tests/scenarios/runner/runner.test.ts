import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { LoadedCard, load } from '../cards'
import { Environment } from '../environment/environment'
import { FakeProjectApi, startFakeProjectApi } from '../scorecard/fake-project-api'
import { Runner, createRunner } from './runner'

const SMOKE_CARD = path.join(__dirname, '..', 'cards', 'smoke.yaml')
const SMOKE = load(SMOKE_CARD)
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
    let api: FakeProjectApi
    let runner: Runner

    const environment: Environment = {
        up: () => Promise.resolve(),
        reset: () => Promise.resolve(duringReset()),
        role: (name) => ({ name, metricsUrl: '' }),
        health: () => Promise.resolve({ healthy: true, down: [] }),
        exits: () => [],
        down: () => Promise.resolve(),
    }

    beforeEach(async () => {
        api = await startFakeProjectApi()
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-runner-'))
        stateDir = path.join(cacheHome, 'posthog-scenarios')
        duringReset = () => undefined
        runner = createRunner(environment, {
            ...process.env,
            XDG_CACHE_HOME: cacheHome,
            DATABASE_URL: PROCESS_DATABASE_URL,
            ...api.credentials,
        })
    })

    afterEach(async () => {
        await runner.down()
        rmSync(cacheHome, { recursive: true, force: true })
        await api.close()
    })

    it.each<[string, () => void, RegExp, unknown]>([
        [
            'seeds through the database the profile names',
            () => undefined,
            /^the run stopped: .*127\.0\.0\.1:1\b/,
            undefined,
        ],
        [
            'keeps the result when its evidence cannot be written',
            () => writeFileSync(stateDir, 'not a directory'),
            /; the evidence could not be written: .*ENOTDIR/,
            undefined,
        ],
        [
            'keeps the published verdict when the scorecard files cannot be written',
            () => {
                api.onCapture = ({ properties }) =>
                    mkdirSync(path.join(String(properties.evidence_dir), 'scorecard-event.json'))
            },
            /^the run stopped: [^;]*$/,
            expect.stringMatching(/^the scorecard files could not be written: EISDIR/),
        ],
    ])('%s', async (_story, arrange, statusReason, scorecardError) => {
        arrange()

        const result = await runner.run(withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }), NEVER_ABORTED)

        expect(result).toMatchObject({
            status: 'invalid',
            statusReason: expect.stringMatching(statusReason),
            scorecardError,
        })
        expect(api.captured.map(({ properties }) => properties)).toEqual([
            expect.objectContaining({ run_id: result.runId, status: 'invalid', status_reason: result.statusReason }),
        ])
    })

    it('produces with the Kafka settings the card profile names', async () => {
        const profile = path.join(cacheHome, 'profile.yaml')
        writeFileSync(
            profile,
            stringify({
                ...SMOKE.profile,
                settings: { DATABASE_URL: PROFILE_DATABASE_URL, KAFKA_PRODUCER_SCENARIO_UNKNOWN: 'on' },
            })
        )

        const result = await runner.run(load(SMOKE_CARD, { profilePath: profile }), NEVER_ABORTED)

        expect(result).toMatchObject({
            status: 'invalid',
            statusReason: expect.stringMatching(/^the run stopped: .*scenario\.unknown/),
        })
    })

    it("keeps only this run's part of each role log", async () => {
        mkdirSync(stateDir, { recursive: true })
        const log = path.join(stateDir, 'cdp-api.log')
        writeFileSync(log, 'line from an earlier run\n')
        duringReset = () => appendFileSync(log, 'line from this run\n')

        const { evidenceDir } = await runner.run(withSettings({}), NEVER_ABORTED)

        expect(readFileSync(path.join(evidenceDir, 'logs', 'cdp-api.log'), 'utf8')).toBe('line from this run\n')
    })
})
