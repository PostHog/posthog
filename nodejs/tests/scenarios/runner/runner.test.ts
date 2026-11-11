import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { KafkaConsumer } from 'node-rdkafka'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { defaultConfig } from '~/common/config/config'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'
import { createKafkaTestTopicName, deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { RawClickHouseEvent } from '~/types'

import { LoadedCard, Profile, load } from '../cards'
import { Environment } from '../environment/environment'
import { RoleSpec, consumerGroupsOf, roleSpecs, secretsOf } from '../environment/roles'
import { cyclotronUrlOf, withPostgres } from '../environment/stack'
import { JournalEntry } from '../judge/judge'
import { ProviderEdge, TruthRecord, startProviderEdge } from '../provider-edge'
import { RunResult, Runner, createRunner } from './runner'

const SMOKE_CARD = path.join(__dirname, '..', 'cards', 'smoke.yaml')
const SMOKE = load(SMOKE_CARD)
const PROCESS_DATABASE_URL = 'postgres://scenario:scenario@127.0.0.1:2/scenario'
const PROFILE_DATABASE_URL = 'postgres://scenario:scenario@127.0.0.1:1/scenario'
const NEVER_ABORTED = new AbortController().signal

const withSettings = (settings: Record<string, string>): LoadedCard => ({
    ...SMOKE,
    profile: { ...SMOKE.profile, settings },
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

type DeliveringRoles = { stop(): Promise<void> }

async function startDeliveringRoles(specs: RoleSpec[], leaveOneJobRunning: boolean): Promise<DeliveringRoles> {
    const worker = specs.find(({ role }) => role === 'cdp-cyclotron-worker-email')!.env
    const [
        {
            topics: [topic],
        },
    ] = consumerGroupsOf(specs)
    const cyclotronUrl = cyclotronUrlOf(specs[0])
    const ses = new SESv2Client({
        endpoint: worker.SES_ENDPOINT,
        region: worker.SES_REGION,
        credentials: { accessKeyId: worker.AWS_ACCESS_KEY_ID!, secretAccessKey: worker.AWS_SECRET_ACCESS_KEY! },
        maxAttempts: 1,
    })
    const signer = new EmailTrackingCodeSigner(worker.ENCRYPTION_SALT_KEYS!, '')
    let jobsToLeaveRunning = leaveOneJobRunning ? 1 : 0
    const failures: unknown[] = []
    let work = Promise.resolve()

    const deliver = async (event: RawClickHouseEvent): Promise<void> => {
        const flows = await withPostgres(
            async (client) =>
                (
                    await client.query<{ id: string; actions: { id: string; type: string }[] }>(
                        "SELECT id, actions FROM posthog_hogflow WHERE team_id = $1 AND status = 'active'",
                        [event.team_id]
                    )
                ).rows,
            worker.DATABASE_URL
        )
        const { email } = parseJSON(event.properties ?? '{}') as { email: string }
        for (const flow of flows) {
            for (const action of flow.actions.filter(({ type }) => type === 'function_email')) {
                const jobId = await withPostgres(
                    async (client) =>
                        (
                            await client.query<{ id: string }>(
                                "INSERT INTO cyclotron_jobs (id, team_id, function_id, queue_name, status, priority, scheduled, created, last_transition) VALUES (gen_random_uuid(), $1, $2, 'email', 'running', 0, now(), now(), now()) RETURNING id",
                                [event.team_id, flow.id]
                            )
                        ).rows[0].id,
                    cyclotronUrl
                )
                await ses.send(
                    new SendEmailCommand({
                        FromEmailAddress: 'flows@www.example.com',
                        Destination: { ToAddresses: [email] },
                        Content: {
                            Simple: {
                                Subject: { Data: 'Scenario delivery' },
                                Body: { Text: { Data: 'Scenario delivery' } },
                                Headers: [
                                    {
                                        Name: 'X-PostHog-Tracking-Code',
                                        Value: signer.generate({
                                            functionId: flow.id,
                                            id: jobId,
                                            teamId: event.team_id,
                                            state: { actionId: action.id },
                                        }),
                                    },
                                ],
                            },
                        },
                    })
                )
                if (jobsToLeaveRunning > 0) {
                    jobsToLeaveRunning -= 1
                } else {
                    await withPostgres(
                        (client) =>
                            client.query("UPDATE cyclotron_jobs SET status = 'completed' WHERE id = $1", [jobId]),
                        cyclotronUrl
                    )
                }
            }
        }
    }

    const consumer = new KafkaConsumer(
        {
            'group.id': `scenario-runner-test-${process.pid}`,
            'metadata.broker.list': worker.KAFKA_HOSTS || defaultConfig.KAFKA_HOSTS,
            'enable.auto.commit': false,
        },
        { 'auto.offset.reset': 'earliest' }
    )
    await new Promise<void>((resolve, reject) => consumer.connect({}, (error) => (error ? reject(error) : resolve())))
    consumer.assign([{ topic, partition: 0, offset: 0 }])
    consumer.on('data', ({ value }) => {
        work = work
            .then(() => deliver(parseJSON(value!.toString()) as RawClickHouseEvent))
            .catch((error: unknown) => {
                failures.push(error)
            })
    })
    consumer.consume()

    return {
        async stop() {
            await new Promise((resolve) => consumer.disconnect(resolve))
            await work
            ses.destroy()
            if (failures.length > 0) {
                throw failures[0]
            }
        },
    }
}

describe('runner through seed, drive and judge', () => {
    const jobsSchema = `scenario_runner_${process.pid}`
    const cyclotronUrl = `${defaultConfig.CYCLOTRON_NODE_DATABASE_URL}${defaultConfig.CYCLOTRON_NODE_DATABASE_URL!.includes('?') ? '&' : '?'}options=${encodeURIComponent(`-c search_path=${jobsSchema}`)}`
    const topic = createKafkaTestTopicName('scenario_runner_events')
    let cacheHome: string
    let env: NodeJS.ProcessEnv
    let edge: ProviderEdge
    let roles: DeliveringRoles | undefined
    let results: RunResult[]

    const environmentOf = (delivering: 'none' | 'all' | 'all, leaving one job running'): Environment => ({
        up: () => Promise.resolve(),
        async reset(settings: Profile['settings']) {
            await roles?.stop()
            roles =
                delivering === 'none'
                    ? undefined
                    : await startDeliveringRoles(
                          roleSpecs(env, edge.url, secretsOf(env), settings),
                          delivering !== 'all'
                      )
        },
        role: (name) => ({ name, metricsUrl: '' }),
        health: () => Promise.resolve({ healthy: true, down: [] }),
        exits: () => [],
        down: async () => {
            await roles?.stop()
            roles = undefined
        },
    })

    const shortSmoke = (): LoadedCard => {
        const card = path.join(cacheHome, 'card.yaml')
        const profile = path.join(cacheHome, 'profile.yaml')
        writeFileSync(
            card,
            stringify({
                ...SMOKE.card,
                drive: { ...SMOKE.card.drive, for: '2s', minOffered: 0.5 },
                convergeWithin: '3s',
            })
        )
        writeFileSync(
            profile,
            stringify({
                name: SMOKE.profile.name,
                traffic: { event_email: { ratePerSecond: 2 } },
                settings: {
                    CDP_EVENTS_CONSUMER_TOPIC: topic,
                    KAFKA_PRODUCER_METADATA_BROKER_LIST: defaultConfig.KAFKA_HOSTS,
                },
            })
        )
        return load(card, { profilePath: profile })
    }

    const evidenceOf = (result: RunResult, file: string): unknown =>
        parseJSON(readFileSync(path.join(result.evidenceDir, file), 'utf8'))

    beforeAll(async () => {
        await ensureKafkaTopics([topic])
        await withPostgres(async (client) => {
            await client.query(`DROP SCHEMA IF EXISTS ${jobsSchema} CASCADE`)
            await client.query(`CREATE SCHEMA ${jobsSchema}`)
            await client.query(`CREATE TABLE ${jobsSchema}.cyclotron_jobs (LIKE public.cyclotron_jobs INCLUDING ALL)`)
        }, defaultConfig.CYCLOTRON_NODE_DATABASE_URL)
    })

    afterAll(async () => {
        await withPostgres(
            (client) => client.query(`DROP SCHEMA IF EXISTS ${jobsSchema} CASCADE`),
            defaultConfig.CYCLOTRON_NODE_DATABASE_URL
        )
        await deleteKafkaTopics([topic])
    })

    beforeEach(async () => {
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-runner-'))
        env = {
            ...process.env,
            XDG_CACHE_HOME: cacheHome,
            DATABASE_URL: defaultConfig.DATABASE_URL,
            CYCLOTRON_NODE_DATABASE_URL: cyclotronUrl,
        }
        edge = await startProviderEdge({ port: 0, trackingKeys: secretsOf(env).encryptionSaltKeys })
        results = []
        await withPostgres((client) => client.query('DELETE FROM cyclotron_jobs'), cyclotronUrl)
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await roles?.stop()
        roles = undefined
        await edge.close()
        const teams = [
            ...new Set(
                results.flatMap((result) =>
                    existsSync(path.join(result.evidenceDir, 'journal.json'))
                        ? (evidenceOf(result, 'journal.json') as JournalEntry[]).map(({ teamId }) => teamId)
                        : []
                )
            ),
        ]
        await withPostgres(async (client) => {
            await client.query('DELETE FROM posthog_hogflow WHERE team_id = ANY($1)', [teams])
            await client.query('DELETE FROM posthog_integration WHERE team_id = ANY($1)', [teams])
            const { rows } = await client.query<{ organization_id: string }>(
                'DELETE FROM posthog_team WHERE id = ANY($1) RETURNING organization_id',
                [teams]
            )
            const organizations = rows.map(({ organization_id }) => organization_id)
            await client.query('DELETE FROM posthog_project WHERE id = ANY($1)', [teams])
            const { rows: members } = await client.query<{ user_id: number }>(
                'DELETE FROM posthog_organizationmembership WHERE organization_id = ANY($1) RETURNING user_id',
                [organizations]
            )
            await client.query('DELETE FROM posthog_user WHERE id = ANY($1)', [members.map(({ user_id }) => user_id)])
            await client.query('DELETE FROM posthog_organization WHERE id = ANY($1)', [organizations])
        }, defaultConfig.DATABASE_URL)
        rmSync(cacheHome, { recursive: true, force: true })
    })

    const run = async (delivering: Parameters<typeof environmentOf>[0]): Promise<RunResult> => {
        const result = await createRunner(environmentOf(delivering), env, { edgeUrl: edge.url }).run(
            shortSmoke(),
            NEVER_ABORTED
        )
        results.push(result)
        return result
    }

    const deliveriesOf = (truth: TruthRecord[]): string[] =>
        truth.map(({ unitId, actionId, status }) => `${unitId}/${actionId}/${status}`).sort()

    it.each<[string, Parameters<typeof environmentOf>[0], () => void, object, boolean]>([
        [
            'passes when the roles deliver every unit and finish every job',
            'all',
            () => undefined,
            { status: 'passed', statusReason: 'every invariant held' },
            true,
        ],
        [
            'fails when a job stays unfinished after every unit was delivered',
            'all, leaving one job running',
            () => undefined,
            { status: 'failed', statusReason: 'not converged: 1 unfinished jobs, 0 units without a delivery record' },
            true,
        ],
        [
            'fails with the undelivered units when no role delivers',
            'none',
            () => undefined,
            {
                status: 'failed',
                statusReason: expect.stringMatching(
                    /^not converged: 0 unfinished jobs, [1-9]\d* units without a delivery record; at_least_once failed: [\w-]+-\d+ email: the edge never received it$/
                ),
                invariants: [{ name: 'at_least_once', passed: false, observed: expect.any(Number) }],
            },
            false,
        ],
        [
            'joins the failed verdict and the producer that did not disconnect',
            'none',
            failNextDisconnect,
            {
                status: 'invalid',
                statusReason: expect.stringMatching(
                    /^not converged: .*; at_least_once failed: .*; the load producer did not disconnect: Local: Timed out$/
                ),
            },
            false,
        ],
    ])(
        '%s',
        async (_story, delivering, arrange, verdict, delivered) => {
            arrange()

            const result = await run(delivering)

            const offered = (evidenceOf(result, 'journal.json') as JournalEntry[]).filter(
                ({ answer }) => answer.accepted
            )
            expect(result).toMatchObject(verdict)
            expect(evidenceOf(result, 'scorecard.json')).toEqual(result)
            expect(deliveriesOf(evidenceOf(result, 'truth.json') as TruthRecord[])).toEqual(
                delivered ? offered.map(({ unitId }) => `${unitId}/email/200`).sort() : []
            )
            expect(offered).not.toHaveLength(0)
        },
        30_000
    )
})
