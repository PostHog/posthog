import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { SESv2Client } from '@aws-sdk/client-sesv2'
import { once } from 'events'
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { AddressInfo, Server, Socket, connect, createServer } from 'net'
import { KafkaConsumer } from 'node-rdkafka'
import os from 'os'
import path from 'path'
import { Client } from 'pg'
import { stringify } from 'yaml'

import { insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { CdpConsumerBaseDeps } from '~/cdp/consumers/cdp-base.consumer'
import { CdpCyclotronWorkerEmail } from '~/cdp/consumers/cdp-cyclotron-worker-email.consumer'
import { CdpCyclotronWorkerHogFlow } from '~/cdp/consumers/cdp-cyclotron-worker-hogflow.consumer'
import { triggersOnEvents } from '~/cdp/consumers/event-name-gate'
import {
    CdpProducerName,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '~/cdp/outputs/producers'
import { template as emailTemplate } from '~/cdp/templates/_destinations/email/email.template'
import { CyclotronJobInvocation } from '~/cdp/types'
import { convertToHogFunctionInvocationGlobals } from '~/cdp/utils'
import { defaultConfig } from '~/common/config/config'
import { GroupReadRepository } from '~/common/groups/repositories/group-repository.interface'
import { KafkaProducer, KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { createKafkaTestTopicName, deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { Hub, PluginsServerConfig, RawClickHouseEvent } from '~/types'

import { LoadedCard, Profile, load } from '../cards'
import { Environment, defaultStateDir } from '../environment/environment'
import { RoleSpec, consumerGroupsOf, roleSpecs, secretsOf } from '../environment/roles'
import { cyclotronUrlOf, scratchSchema, withPostgres } from '../environment/stack'
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
        edgeUrl: () => 'http://127.0.0.1:1',
        role: (name) => ({ name, metricsUrl: '' }),
        dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
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
            'seeds through the database the profile builds from its connection settings',
            () => undefined,
            withSettings({
                DATABASE_URL: '',
                POSTHOG_DB_NAME: 'scenario',
                POSTHOG_POSTGRES_HOST: '127.0.0.1',
                POSTHOG_POSTGRES_PORT: '3',
            }),
            /^the run stopped: .*127\.0\.0\.1:3\b/,
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

    it.each<[string, boolean, AbortSignal, RegExp]>([
        ['when a seed insert waits on a table lock', true, NEVER_ABORTED, /statement timeout/],
        ['when the run was interrupted before seeding', false, AbortSignal.abort(), /aborted/],
    ])(
        'stops seeding without a fixture %s',
        async (_story, lockOrganizations, signal, statusReason) => {
            const schema = scratchSchema(defaultConfig.DATABASE_URL, `scenario_seed_${process.pid}`, [
                'posthog_organization',
            ])
            await schema.create()
            const holder = new Client({ connectionString: schema.url })
            await holder.connect()
            try {
                if (lockOrganizations) {
                    await holder.query('BEGIN')
                    await holder.query('LOCK TABLE posthog_organization IN ACCESS EXCLUSIVE MODE')
                }

                const result = await runner.run(withSettings({ DATABASE_URL: schema.url }), signal)

                await holder.query('ROLLBACK')
                const { rows } = await holder.query('SELECT id FROM posthog_organization')
                expect(result).toMatchObject({
                    status: 'invalid',
                    statusReason: expect.stringMatching(new RegExp(`^the run stopped: .*${statusReason.source}`)),
                })
                expect(rows).toEqual([])
            } finally {
                await holder.end()
                await schema.drop()
            }
        },
        20_000
    )

    type Stall = 'startup' | 'query'

    const stalling = async (
        stall: Stall,
        onStalled: () => void
    ): Promise<{ server: Server; clients: Socket[]; sockets: Socket[] }> => {
        const database = new URL(defaultConfig.DATABASE_URL)
        const clients: Socket[] = []
        const sockets: Socket[] = []
        const server = createServer((client) => {
            clients.push(client)
            sockets.push(client)
            if (stall === 'startup') {
                client.once('data', onStalled).resume()
                return
            }
            const upstream = connect(Number(database.port), database.hostname)
            sockets.push(upstream)
            let ready = false
            let pending = Buffer.alloc(0)
            upstream.on('data', (chunk: Buffer) => {
                pending = Buffer.concat([pending, chunk])
                while (pending.length >= 5 && pending.length >= 1 + pending.readUInt32BE(1)) {
                    ready ||= pending[0] === 0x5a
                    pending = pending.subarray(1 + pending.readUInt32BE(1))
                }
                client.write(chunk)
            })
            upstream.on('end', () => client.end())
            client.on('data', (chunk: Buffer) => {
                if (ready) {
                    onStalled()
                    return
                }
                upstream.write(chunk)
            })
            client.on('end', () => upstream.end())
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        return { server, clients, sockets }
    }

    it.each<[string, Stall, unknown[] | undefined, string]>([
        ['the database never answers its startup', 'startup', undefined, 'seeding did not finish within 2000 ms'],
        ['the database never answers a seed query', 'query', undefined, 'seeding did not finish within 2000 ms'],
        [
            'the run is interrupted while the database never answers its startup',
            'startup',
            [],
            'seeding was interrupted',
        ],
        [
            'the run is interrupted without a reason while the database never answers its startup',
            'startup',
            [null],
            'seeding was interrupted',
        ],
    ])(
        'ends the seeding stage and requires a restart when %s',
        async (_story, stall, abortWith, why) => {
            const interrupt = new AbortController()
            let stalled = false
            const { server, clients, sockets } = await stalling(stall, () => {
                stalled = true
                if (abortWith !== undefined) {
                    interrupt.abort(...abortWith)
                }
            })
            try {
                const proxied = new URL(defaultConfig.DATABASE_URL)
                proxied.hostname = '127.0.0.1'
                proxied.port = String((server.address() as AddressInfo).port)
                const bounded = createRunner(
                    environment,
                    { ...process.env, XDG_CACHE_HOME: cacheHome, DATABASE_URL: PROCESS_DATABASE_URL },
                    { seedWithinMs: 2000 }
                )

                const result = await bounded.run(withSettings({ DATABASE_URL: proxied.toString() }), interrupt.signal)

                expect(stalled).toBe(true)
                expect(result).toMatchObject({
                    status: 'invalid',
                    statusReason: `the run stopped: ${why}; its connections were destroyed, restart required`,
                })
                await Promise.all(clients.map((client) => (client.closed ? Promise.resolve() : once(client, 'close'))))
                await expect(
                    bounded.run(withSettings({ DATABASE_URL: proxied.toString() }), NEVER_ABORTED)
                ).rejects.toThrow(
                    /^The seeding stage of run \S+ was cut short .* Restart the runner, then run the card again\.$/
                )
            } finally {
                sockets.forEach((socket) => socket.destroy())
                await new Promise((resolve) => server.close(resolve))
            }
        },
        20_000
    )

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

type Cdp = { hub: Hub; hogflow: CdpCyclotronWorkerHogFlow; email: CdpCyclotronWorkerEmail }

const MOST_LEGS_PER_RUN = 10

const discardingProducer: KafkaProducer = {
    produce: () => Promise.resolve(),
    queueMessages: () => Promise.resolve(),
    disconnect: () => Promise.resolve(),
    checkConnection: () => Promise.resolve(),
    checkTopicExists: () => Promise.resolve(),
}

const noPersons: PersonReadRepository = {
    fetchPerson: () => Promise.resolve(undefined),
    fetchPersonsByDistinctIds: () => Promise.resolve([]),
    fetchPersonsByPersonIds: () => Promise.resolve([]),
    fetchDistinctIdsForPersons: () => Promise.resolve({}),
}

const noGroups: GroupReadRepository = {
    fetchGroupsByKeys: () => Promise.resolve([]),
    fetchGroupTypesByTeamIds: () => Promise.resolve({}),
    fetchGroupTypesByProjectIds: () => Promise.resolve({}),
}

async function startCdp(config: Partial<PluginsServerConfig>): Promise<Cdp> {
    const hub = await createHub(config)
    await insertHogFunctionTemplate(hub.postgres, emailTemplate)
    const deps: CdpConsumerBaseDeps = {
        postgres: hub.postgres,
        pubSub: hub.pubSub,
        encryptedFields: hub.encryptedFields,
        teamManager: hub.teamManager,
        integrationManager: hub.integrationManager,
        cdpProducerRegistry: new KafkaProducerRegistry<CdpProducerName>({
            [WARPSTREAM_INGESTION_PRODUCER]: discardingProducer,
            [WARPSTREAM_CYCLOTRON_PRODUCER]: discardingProducer,
            [WAREHOUSE_PRODUCER]: discardingProducer,
        }),
        internalCaptureService: new InternalCaptureService(hub),
        personRepository: noPersons,
        geoipService: hub.geoipService,
        groupRepository: noGroups,
        quotaLimiting: hub.quotaLimiting,
        emailValidationValkey: null,
        frequencyCapValkey: null,
    }
    return {
        hub,
        hogflow: new CdpCyclotronWorkerHogFlow(hub, deps, createMockJobQueue()),
        email: new CdpCyclotronWorkerEmail(hub, deps, createMockJobQueue()),
    }
}

async function stopCdp({ hub, hogflow, email }: Cdp): Promise<void> {
    await Promise.all([hogflow.stop(), email.stop()])
    await closeHub(hub)
}

async function runToItsEnd(cdp: Cdp, invocation: CyclotronJobInvocation): Promise<void> {
    let job = invocation
    for (let leg = 0; leg < MOST_LEGS_PER_RUN; leg++) {
        const worker = job.queue === 'hogflow' || job.queue === 'email' ? cdp[job.queue] : undefined
        if (!worker) {
            throw new Error(`No role works the ${job.queue} queue of flow ${job.functionId}`)
        }
        const [result] = await worker.processInvocations([job])
        if (result.error !== undefined) {
            throw new Error(`Flow ${job.functionId} failed on the ${job.queue} queue: ${String(result.error)}`)
        }
        if (result.finished) {
            return
        }
        job = { ...result.invocation, state: parseJSON(JSON.stringify(result.invocation.state)) }
    }
    throw new Error(`Flow ${invocation.functionId} did not finish within ${MOST_LEGS_PER_RUN} legs`)
}

async function startDeliveringRoles(
    cdp: Cdp,
    specs: RoleSpec[],
    leaveOneJobRunning: boolean
): Promise<DeliveringRoles> {
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
    cdp.email.emailService.sesV2Client = ses
    let jobsToLeaveRunning = leaveOneJobRunning ? 1 : 0
    const failures: unknown[] = []
    let work = Promise.resolve()

    const deliver = async (event: RawClickHouseEvent): Promise<void> => {
        const team = await cdp.hub.teamManager.getTeam(event.team_id)
        if (!team) {
            throw new Error(`No team ${event.team_id}`)
        }
        const flows = (await cdp.hogflow.hogFlowManager.getHogFlowsForTeam(team.id)).filter(triggersOnEvents)
        const { invocations } = await cdp.hogflow.hogFlowExecutor.buildHogFlowInvocations(
            flows,
            convertToHogFunctionInvocationGlobals(event, team, cdp.hub.SITE_URL)
        )
        for (const invocation of invocations) {
            await withPostgres(
                (client) =>
                    client.query(
                        "INSERT INTO cyclotron_jobs (id, team_id, function_id, queue_name, status, priority, scheduled, created, last_transition) VALUES ($1, $2, $3, $4, 'running', 0, now(), now(), now())",
                        [invocation.id, invocation.teamId, invocation.functionId, invocation.queue]
                    ),
                cyclotronUrl
            )
            await runToItsEnd(cdp, invocation)
            if (jobsToLeaveRunning > 0) {
                jobsToLeaveRunning -= 1
            } else {
                await withPostgres(
                    (client) =>
                        client.query("UPDATE cyclotron_jobs SET status = 'completed' WHERE id = $1", [invocation.id]),
                    cyclotronUrl
                )
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
    const end = await new Promise<number>((resolve, reject) =>
        consumer.queryWatermarkOffsets(topic, 0, 5000, (error, offsets) =>
            error ? reject(error) : resolve(offsets.highOffset)
        )
    )
    consumer.assign([{ topic, partition: 0, offset: end }])
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
    const jobsSchema = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_runner_${process.pid}`, [
        'cyclotron_jobs',
    ])
    const cyclotronUrl = jobsSchema.url
    const topic = createKafkaTestTopicName('scenario_runner_events')
    let cacheHome: string
    let env: NodeJS.ProcessEnv
    let edge: ProviderEdge
    let roles: DeliveringRoles | undefined
    let results: RunResult[]
    let cdp: Cdp

    const environmentOf = (delivering: 'none' | 'all' | 'all, leaving one job running'): Environment => ({
        up: () => Promise.resolve(),
        async reset(settings: Profile['settings']) {
            await roles?.stop()
            roles =
                delivering === 'none'
                    ? undefined
                    : await startDeliveringRoles(
                          cdp,
                          roleSpecs(env, edge.url, secretsOf(env), defaultStateDir(env), settings),
                          delivering !== 'all'
                      )
        },
        edgeUrl: () => edge.url,
        role: (name) => ({ name, metricsUrl: '' }),
        dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
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
        await jobsSchema.create()
        cdp = await startCdp({
            DATABASE_URL: defaultConfig.DATABASE_URL,
            ENCRYPTION_SALT_KEYS: secretsOf(process.env).encryptionSaltKeys,
            CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: 10_000,
        })
    })

    afterAll(async () => {
        await stopCdp(cdp)
        await jobsSchema.drop()
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
        try {
            await cleanUp()
        } finally {
            const stopping = roles
            roles = undefined
            await stopping?.stop()
        }
    })

    const cleanUp = async (): Promise<void> => {
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
    }

    const run = async (delivering: Parameters<typeof environmentOf>[0]): Promise<RunResult> => {
        const result = await createRunner(environmentOf(delivering), env).run(shortSmoke(), NEVER_ABORTED)
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
