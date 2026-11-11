import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'

import { LoadedCard, load } from '../cards'
import { Environment } from '../environment/environment'
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
    let runner: Runner

    const environment: Environment = {
        up: () => Promise.resolve(),
        reset: () => Promise.resolve(duringReset()),
        role: (name) => ({ name, metricsUrl: '' }),
        health: () => Promise.resolve({ healthy: true, down: [] }),
        exits: () => [],
        down: () => Promise.resolve(),
    }

    beforeEach(() => {
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-runner-'))
        stateDir = path.join(cacheHome, 'posthog-scenarios')
        duringReset = () => undefined
        runner = createRunner(environment, {
            ...process.env,
            XDG_CACHE_HOME: cacheHome,
            DATABASE_URL: PROCESS_DATABASE_URL,
        })
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await runner.down()
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

        const result = await runner.run(loaded, NEVER_ABORTED)

        expect(result).toMatchObject({ status: 'invalid', statusReason: expect.stringMatching(statusReason) })
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

    const failNextDisconnect = (): void => {
        const disconnect = KafkaProducerWrapper.prototype.disconnect
        jest.spyOn(KafkaProducerWrapper.prototype, 'disconnect').mockImplementationOnce(async function (
            this: KafkaProducerWrapper
        ) {
            await disconnect.call(this)
            throw new Error('Local: Timed out')
        })
    }

    it('keeps the result and its evidence when the load producer cannot flush on disconnect', async () => {
        failNextDisconnect()

        const result = await runner.run(withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }), NEVER_ABORTED)

        const statusReason = expect.stringMatching(
            /^the run stopped: .*127\.0\.0\.1:1\b.*; the load producer did not disconnect: Local: Timed out$/
        )
        expect(result).toMatchObject({ status: 'invalid', statusReason })
        expect(parseJSON(readFileSync(path.join(result.evidenceDir, 'scorecard.json'), 'utf8'))).toMatchObject({
            status: 'invalid',
            statusReason,
        })
    })

    it('refuses the next card on a runner whose load producer did not disconnect', async () => {
        failNextDisconnect()
        const stuck = await runner.run(withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }), NEVER_ABORTED)

        await expect(runner.run(withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }), NEVER_ABORTED)).rejects.toThrow(
            `The load producer of run ${stuck.runId} did not disconnect and may still send its buffered messages into this card. Restart the runner, then run the card again.`
        )
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
