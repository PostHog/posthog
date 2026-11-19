import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { SESv2Client } from '@aws-sdk/client-sesv2'
import { randomUUID } from 'crypto'
import { once } from 'events'
import fs, {
    appendFileSync,
    existsSync,
    mkdirSync,
    mkdtempSync,
    readFileSync,
    readdirSync,
    rmSync,
    statSync,
    utimesSync,
    writeFileSync,
} from 'fs'
import http from 'http'
import { AddressInfo, Server, Socket, connect, createServer } from 'net'
import { KafkaConsumer } from 'node-rdkafka'
import os from 'os'
import path from 'path'
import { Client } from 'pg'
import { Registry, collectDefaultMetrics } from 'prom-client'
// eslint-disable-next-line no-restricted-imports
import { ProxyAgent } from 'undici'
import { stringify } from 'yaml'

import { insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { CdpConsumerBaseDeps } from '~/cdp/consumers/cdp-base.consumer'
import { CdpCyclotronWorkerEmail } from '~/cdp/consumers/cdp-cyclotron-worker-email.consumer'
import { CdpCyclotronWorkerHogFlow } from '~/cdp/consumers/cdp-cyclotron-worker-hogflow.consumer'
import { triggersOnEvents } from '~/cdp/consumers/event-name-gate'
import {
    CdpProducerName,
    MSK_CDP_INTAKE_PRODUCER,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CYCLOTRON_INTAKE_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '~/cdp/outputs/producers'
import { template as emailTemplate } from '~/cdp/templates/_destinations/email/email.template'
import { template as webhookTemplate } from '~/cdp/templates/_destinations/webhook/webhook.template'
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
import { _fetch, fetch } from '~/common/utils/request'
import { createKafkaTestTopicName, deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { Hub, PluginsServerConfig, RawClickHouseEvent } from '~/types'

import { seedBacklog } from '../backlog/backlog'
import { Backlog, CdpRole, LoadedCard, Named, Profile, ValveEntry, load } from '../cards'
import { FakeCloud } from '../cloud/fake-cloud'
import { pinClockAfterMinuteStart } from '../cloud/fixtures'
import { Environment, RoleExit, createEnvironment, defaultStateDir } from '../environment/environment'
import { Role, RoleSpec, SCENARIO_SESSION_PREFIX, consumerGroupsOf, roleSpecs, secretsOf } from '../environment/roles'
import { RESIDENT_TEAMS_FROM, cyclotronUrlOf, scratchSchema, withPostgres } from '../environment/stack'
import { KafkaGroup, WORKFLOWS_ADAPTER, Wiring, wiringOf } from '../environment/topology'
import { JournalEntry } from '../judge/judge'
import { main } from '../main'
import { ProviderEdge, TruthRecord, WEBHOOK_HOST, startProviderEdge } from '../provider-edge'
import { FakeProjectApi, startFakeProjectApi } from '../scorecard/fake-project-api'
import { STORE_URL } from '../store/client'
import { TestStore, UNREACHABLE_STORE, startTestStore, storeEnvOf } from '../store/test-store'
import { LIVE_FILE, LiveRecord } from './live'
import { RunResult, Runner, createRunner } from './runner'
import { EXIT_CODE, exitCodeOf } from './status'

jest.mock('~/common/utils/request', () => {
    const actual = jest.requireActual('~/common/utils/request')
    return { ...actual, fetch: jest.fn(actual.fetch) }
})

const SMOKE_CARD = path.join(__dirname, '..', 'cards', 'smoke.yaml')
const SMOKE = load(SMOKE_CARD)
const PROCESS_DATABASE_URL = 'postgres://scenario:scenario@127.0.0.1:2/scenario'
const PROFILE_DATABASE_URL = 'postgres://scenario:scenario@127.0.0.1:1/scenario'
const NEVER_ABORTED = new AbortController().signal
const { [STORE_URL]: _developerStore, ...processEnv } = process.env

const withSettings = (settings: Record<string, string>): LoadedCard => ({
    ...SMOKE,
    profile: { ...SMOKE.profile, settings },
})

let processMetrics: { url: string; server: http.Server }
let janitor: { scrapes: number; resetsAfterFirstScrape: number }

beforeAll(async () => {
    const registry = new Registry()
    collectDefaultMetrics({ register: registry })
    const server = http.createServer(async (req, res) => {
        const resets = req.url?.includes('role=cdp-cyclotron-v2-janitor')
            ? [`cdp_cyclotron_v2_janitor_stalled ${janitor.scrapes++ === 0 ? 0 : janitor.resetsAfterFirstScrape}`]
            : []
        res.end([await registry.metrics(), ...resets].join('\n'))
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    processMetrics = { url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/_metrics`, server }
})

afterAll(async () => {
    processMetrics.server.closeAllConnections()
    await new Promise<void>((resolve) => processMetrics.server.close(() => resolve()))
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

const joinedGroupsOf = (specs: RoleSpec[]): KafkaGroup[] =>
    specs.flatMap((spec) =>
        consumerGroupsOf([spec]).map(({ group, topics }) => ({
            group,
            partitions: topics.map((topic) => ({ topic, lag: 0, client: `${SCENARIO_SESSION_PREFIX}${spec.role}` })),
        }))
    )

describe('runner', () => {
    let cacheHome: string
    let stateDir: string
    let duringReset: () => void
    let api: FakeProjectApi
    let runner: Runner

    const environment: Environment = {
        up: () => Promise.resolve(),
        reset: () => Promise.resolve(duringReset()),
        edgeUrl: () => 'http://127.0.0.1:1',
        role: (name) => ({ name, replica: 0, url: 'http://127.0.0.1:1', metricsUrl: processMetrics.url }),
        roles: () =>
            CdpRole.options.map((name) => ({
                name,
                replica: 0,
                url: 'http://127.0.0.1:1',
                metricsUrl: processMetrics.url,
            })),
        actuate: () => Promise.reject(new Error('these runs schedule no valves')),
        writerCpu: () => Promise.reject(new Error('these runs read no writer CPU')),
        dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
        exits: () => [],
        groupLag: () => Promise.resolve(0),
        wiring: () =>
            Promise.resolve(
                wiringOf({
                    adapter: WORKFLOWS_ADAPTER,
                    specs: roleSpecs(process.env, { url: 'http://edge' }, secretsOf({}), stateDir),
                    groups: joinedGroupsOf(roleSpecs(process.env, { url: 'http://edge' }, secretsOf({}), stateDir)),
                    clients: [],
                    recordedAt: new Date(),
                })
            ),
        down: () => Promise.resolve(),
    }

    beforeEach(async () => {
        api = await startFakeProjectApi()
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-runner-'))
        stateDir = path.join(cacheHome, 'posthog-scenarios')
        duringReset = () => undefined
        runner = createRunner(
            environment,
            {
                ...processEnv,
                XDG_CACHE_HOME: cacheHome,
                DATABASE_URL: PROCESS_DATABASE_URL,
                ...api.credentials,
            },
            { topologyEveryMs: 10 }
        )
    })

    afterEach(async () => {
        jest.useRealTimers()
        jest.restoreAllMocks()
        await runner.down()
        rmSync(cacheHome, { recursive: true, force: true })
        await api.close()
    })

    it.each<[string, () => void, LoadedCard, RegExp, unknown]>([
        [
            'seeds through the database the profile names',
            () => undefined,
            withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }),
            /^the run stopped: .*127\.0\.0\.1:1\b/,
            undefined,
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
            undefined,
        ],
        [
            'keeps the result when its evidence cannot be written',
            () => writeFileSync(stateDir, 'not a directory'),
            withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }),
            /; the evidence could not be written: .*ENOTDIR/,
            undefined,
        ],
        [
            'fails the run when the disk fills while its scorecard is written',
            () => {
                const write = fs.writeFileSync
                jest.spyOn(fs, 'writeFileSync').mockImplementation((file, data, options) => {
                    if (!String(file).endsWith('scorecard.json.partial')) {
                        return write(file, data, options)
                    }
                    write(file, String(data).slice(0, 8))
                    throw Object.assign(new Error('ENOSPC: no space left on device, write'), { code: 'ENOSPC' })
                })
            },
            withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }),
            /; the evidence could not be written: ENOSPC/,
            undefined,
        ],
    ])('%s', async (_story, arrange, loaded, statusReason, scorecardError) => {
        arrange()

        const result = await runner.run(loaded, NEVER_ABORTED)

        expect(result).toMatchObject({
            status: 'invalid',
            statusReason: expect.stringMatching(statusReason),
            scorecardError,
        })
        expect(api.captured.map(({ properties }) => properties)).toEqual([
            expect.objectContaining({ run_id: result.runId, status: 'invalid', status_reason: result.statusReason }),
        ])
    })

    it('runs one card under the run id of its run manifest', async () => {
        const runId = '6b0c8f4e-2d1a-4c55-9a7e-1f3b5d7e9a2c'
        const manifest = path.join(cacheHome, 'manifest.json')
        writeFileSync(
            manifest,
            JSON.stringify({
                runId,
                account: '000000000000',
                stackName: `scn-${runId}`,
                schedules: [],
                expiresAt: '2026-01-05T16:00:00.000Z',
            })
        )
        const onHost = createRunner(environment, {
            ...processEnv,
            XDG_CACHE_HOME: cacheHome,
            DATABASE_URL: PROCESS_DATABASE_URL,
            SCENARIO_RUN_MANIFEST: manifest,
            ...api.credentials,
        })
        const loaded = withSettings({ DATABASE_URL: PROFILE_DATABASE_URL })

        const result = await onHost.run(loaded, NEVER_ABORTED)

        expect(result).toMatchObject({ runId, evidenceDir: path.join(stateDir, runId) })
        expect(api.captured.map(({ properties }) => properties.run_id)).toEqual([runId])
        await expect(onHost.run(loaded, NEVER_ABORTED)).rejects.toThrow(
            `This runner already ran run ${runId} from its run manifest; a run host runs one card per manifest.`
        )
    })

    it('saves the verdict with the event it publishes once, before publication, and leaves it as written', async () => {
        let onDisk: unknown
        api.onCapture = ({ properties }) => {
            onDisk = parseJSON(readFileSync(path.join(String(properties.evidence_dir), 'scorecard.json'), 'utf8'))
        }

        const result = await runner.run(withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }), NEVER_ABORTED)

        expect(result.recorded).toBe(true)
        expect(onDisk).toEqual({
            ...result,
            recorded: undefined,
            captured: undefined,
            scorecardError: undefined,
            host: os.hostname(),
            event: api.captured[0].properties,
        })
        expect(parseJSON(readFileSync(path.join(result.evidenceDir, 'scorecard.json'), 'utf8'))).toEqual(onDisk)
        expect(readdirSync(result.evidenceDir).filter((file) => file.startsWith('scorecard'))).toEqual([
            'scorecard.json',
        ])
    })

    describe('reporting to the run store', () => {
        let store: TestStore

        const runnerWith = (storeEnv: NodeJS.ProcessEnv): Runner =>
            createRunner(environment, {
                ...processEnv,
                XDG_CACHE_HOME: cacheHome,
                DATABASE_URL: PROCESS_DATABASE_URL,
                ...api.credentials,
                ...storeEnv,
            })

        beforeAll(async () => {
            store = await startTestStore('runner')
        })

        afterAll(() => store.close())

        it('stores the scorecard it publishes, with its adapters and the host it ran on', async () => {
            const result = await runnerWith(store.envOf(cacheHome)).run(
                withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }),
                NEVER_ABORTED
            )

            expect(result).toMatchObject({ recorded: true, stored: true })
            expect(await store.read(result.runId)).toMatchObject({
                scorecard: api.captured[0].properties,
                adapters: ['workflows'],
                owners: [],
                host: os.hostname(),
            })
        })

        it('keeps its status when the run store is down, and publish --all stores the run later', async () => {
            jest.spyOn(process.stdout, 'write').mockReturnValue(true)
            const loaded = withSettings({ DATABASE_URL: PROFILE_DATABASE_URL })
            const withoutStore = await runner.run(loaded, NEVER_ABORTED)
            const result = await runnerWith(storeEnvOf(cacheHome, UNREACHABLE_STORE)).run(loaded, NEVER_ABORTED)

            expect(result).toMatchObject({
                recorded: true,
                storeError: expect.stringMatching(/^the run store did not answer/),
            })
            expect(result.stored).toBeUndefined()
            expect({ status: result.status, statusReason: result.statusReason, exitCode: exitCodeOf(result) }).toEqual({
                status: withoutStore.status,
                statusReason: withoutStore.statusReason,
                exitCode: exitCodeOf(withoutStore),
            })

            const published = await main(['publish', '--all'], {
                ...processEnv,
                XDG_CACHE_HOME: cacheHome,
                ...store.envOf(cacheHome),
            })

            expect(published).toBe(EXIT_CODE.passed)
            expect(await store.read(result.runId)).toMatchObject({
                scorecard: api.captured[1].properties,
                host: os.hostname(),
            })
        })
    })

    it.each<[string, boolean, AbortSignal, RegExp]>([
        ['when a seed insert waits on a table lock', true, NEVER_ABORTED, /statement timeout/],
        ['when the run was interrupted before seeding', false, AbortSignal.abort(), /seeding was interrupted/],
        [
            'when the run was interrupted before seeding without a reason',
            false,
            AbortSignal.abort(null),
            /seeding was interrupted/,
        ],
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
                    { ...processEnv, XDG_CACHE_HOME: cacheHome, DATABASE_URL: PROCESS_DATABASE_URL },
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

    it('stops the live heartbeat of a run that fails before it writes its end record', async () => {
        jest.useFakeTimers({
            doNotFake: [
                'Date',
                'hrtime',
                'nextTick',
                'performance',
                'queueMicrotask',
                'setImmediate',
                'clearImmediate',
                'setTimeout',
                'clearTimeout',
            ],
        })
        jest.spyOn(os, 'cpus').mockImplementation(() => {
            throw new Error('the host hides its CPUs')
        })

        await expect(runner.run(withSettings({ DATABASE_URL: PROFILE_DATABASE_URL }), NEVER_ABORTED)).rejects.toThrow(
            'the host hides its CPUs'
        )

        const [live] = readdirSync(stateDir)
            .map((name) => path.join(stateDir, name, LIVE_FILE))
            .filter((file) => existsSync(file))
        const minuteAgo = new Date(Date.now() - 60_000)
        utimesSync(live, minuteAgo, minuteAgo)
        jest.advanceTimersByTime(5000)
        expect(statSync(live).mtimeMs).toBe(minuteAgo.getTime())
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
    await insertHogFunctionTemplate(hub.postgres, webhookTemplate)
    const deps: CdpConsumerBaseDeps = {
        postgres: hub.postgres,
        pubSub: hub.pubSub,
        encryptedFields: hub.encryptedFields,
        teamManager: hub.teamManager,
        integrationManager: hub.integrationManager,
        cdpProducerRegistry: new KafkaProducerRegistry<CdpProducerName>({
            [WARPSTREAM_INGESTION_PRODUCER]: discardingProducer,
            [WARPSTREAM_CYCLOTRON_PRODUCER]: discardingProducer,
            [WARPSTREAM_CYCLOTRON_INTAKE_PRODUCER]: discardingProducer,
            [WAREHOUSE_PRODUCER]: discardingProducer,
            [MSK_CDP_INTAKE_PRODUCER]: discardingProducer,
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
    let throughTheEdge: ProxyAgent
    let api: FakeProjectApi
    let roles: DeliveringRoles | undefined
    let results: RunResult[]
    let cdp: Cdp

    let handles: RoleSpec[] = []
    let exits: RoleExit[]
    let killExits: (role: Role) => RoleExit[]
    let failedWiringReads = 0
    let cyclotronJoinsAtRead = 0
    let wiringReads = 0
    let exitsAtWiringRead: RoleExit[] = []
    let wiringChurns = false
    let groupsJoinAtRead = 0
    let interruptAtWiringRead: { read: number; interrupt: AbortController } | undefined
    let hangsFromWiringRead = Infinity
    const exitOfTheKill = (role: Role): RoleExit[] => [
        { role, replica: 0, at: new Date().toISOString(), code: null, signal: 'SIGKILL', byValve: true },
    ]

    const environmentOf = (
        delivering: 'none' | 'all' | 'all, leaving one job running',
        roleUrl = 'http://127.0.0.1:1'
    ): Environment => ({
        up: () => Promise.resolve(),
        async reset(settings: Profile['settings'], replicas: Profile['replicas'] = {}) {
            handles = roleSpecs(env, { url: edge.url }, secretsOf(env), defaultStateDir(env), {}, undefined, replicas)
            await roles?.stop()
            roles =
                delivering === 'none'
                    ? undefined
                    : await startDeliveringRoles(
                          cdp,
                          roleSpecs(env, { url: edge.url }, secretsOf(env), defaultStateDir(env), settings),
                          delivering !== 'all'
                      )
        },
        edgeUrl: () => edge.url,
        role: (name) => ({ name, replica: 0, url: roleUrl, metricsUrl: processMetrics.url }),
        roles: () =>
            handles.map(({ role, replica }) => ({
                name: role,
                replica,
                url: roleUrl,
                metricsUrl: `${processMetrics.url}?replica=${replica}&role=${role}`,
            })),
        actuate(action) {
            exits.push(...(action.kind === 'kill' ? killExits(action.role) : []))
            return Promise.resolve({ observed: () => Promise.resolve(true), release: () => Promise.resolve() })
        },
        dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
        exits: () => [...exits],
        groupLag: () => Promise.resolve(0),
        wiring: (signal) => {
            const read = wiringReads++
            const interrupt = interruptAtWiringRead?.read === read ? interruptAtWiringRead.interrupt : undefined
            if (read >= hangsFromWiringRead) {
                return new Promise((_, reject) => {
                    signal.addEventListener('abort', () => reject(signal.reason))
                    interrupt?.abort()
                })
            }
            interrupt?.abort()
            exits.push(...exitsAtWiringRead.splice(0))
            if (read < failedWiringReads) {
                return Promise.reject(new Error('rpk group list timed out'))
            }
            return Promise.resolve(
                wiringOf({
                    adapter: WORKFLOWS_ADAPTER,
                    specs: handles,
                    groups: read >= groupsJoinAtRead ? joinedGroupsOf(handles) : [],
                    clients:
                        read >= cyclotronJoinsAtRead
                            ? [
                                  {
                                      application: 'scenario-cdp-cyclotron-worker-hogflow',
                                      database: wiringChurns ? `cyclotron-${read}` : 'cyclotron',
                                      connections: 1,
                                  },
                              ]
                            : [],
                    recordedAt: new Date(),
                })
            )
        },
        writerCpu: () => Promise.reject(new Error('a local run reads no writer CPU')),
        down: async () => {
            await roles?.stop()
            roles = undefined
        },
    })

    const shortSmoke = (
        valves: ValveEntry[] = [],
        traffic = 'event_email',
        {
            replicas = {},
            parks = 0,
            invariants = SMOKE.card.invariants,
            measures = SMOKE.card.measure,
            load: loadTargets,
            backlog,
            ramp,
            bars = [],
        }: {
            replicas?: Profile['replicas']
            parks?: number
            invariants?: Named[]
            measures?: Named[]
            load?: Profile['load']
            backlog?: Backlog
            ramp?: LoadedCard['card']['drive']['ramp']
            bars?: Named[]
        } = {}
    ): LoadedCard => {
        const card = path.join(cacheHome, 'card.yaml')
        const profile = path.join(cacheHome, 'profile.yaml')
        writeFileSync(
            card,
            stringify({
                ...SMOKE.card,
                drive: { ...SMOKE.card.drive, for: '2s', minOffered: 0.5, traffic: [{ name: traffic }], ramp },
                invariants,
                measure: measures,
                bars,
                valves,
                convergeWithin: valves.length > 0 ? '8s' : '3s',
            })
        )
        writeFileSync(
            profile,
            stringify({
                name: SMOKE.profile.name,
                traffic: { [traffic]: { ratePerSecond: 2, parks } },
                replicas,
                ...(loadTargets ? { load: loadTargets } : {}),
                ...(backlog ? { backlog } : {}),
                settings: {
                    CDP_EVENTS_CONSUMER_TOPIC: topic,
                    KAFKA_PRODUCER_METADATA_BROKER_LIST: defaultConfig.KAFKA_HOSTS,
                    CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: '0',
                    CYCLOTRON_NODE_JANITOR_CLEANUP_INTERVAL_MS: '0',
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
        failedWiringReads = 0
        cyclotronJoinsAtRead = 0
        wiringReads = 0
        exitsAtWiringRead = []
        wiringChurns = false
        groupsJoinAtRead = 0
        interruptAtWiringRead = undefined
        hangsFromWiringRead = Infinity
        api = await startFakeProjectApi()
        cacheHome = mkdtempSync(path.join(os.tmpdir(), 'scenario-runner-'))
        env = {
            ...processEnv,
            XDG_CACHE_HOME: cacheHome,
            DATABASE_URL: defaultConfig.DATABASE_URL,
            CYCLOTRON_NODE_DATABASE_URL: cyclotronUrl,
            ...api.credentials,
        }
        edge = await startProviderEdge({
            port: 0,
            trackingKeys: secretsOf(env).encryptionSaltKeys,
            caDir: path.join(cacheHome, 'edge-ca'),
        })
        throughTheEdge = new ProxyAgent({
            uri: edge.url,
            proxyTunnel: true,
            requestTls: { ca: readFileSync(edge.caCertPath!) },
        })
        jest.mocked(fetch).mockImplementation((url, options) => _fetch(url, options, throughTheEdge))
        results = []
        exits = []
        killExits = exitOfTheKill
        janitor = { scrapes: 0, resetsAfterFirstScrape: 0 }
        await withPostgres((client) => client.query('DELETE FROM cyclotron_jobs'), cyclotronUrl)
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        jest.useRealTimers()
        try {
            await cleanUp()
        } finally {
            const stopping = roles
            roles = undefined
            await stopping?.stop()
        }
    })

    const cleanUp = async (): Promise<void> => {
        await throughTheEdge.close()
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
        await api.close()
    }

    const run = async (
        delivering: Parameters<typeof environmentOf>[0],
        valves: ValveEntry[] = [],
        traffic?: string,
        options: Parameters<typeof shortSmoke>[2] = {},
        signal: AbortSignal = NEVER_ABORTED
    ): Promise<RunResult> => {
        const result = await createRunner(environmentOf(delivering), env, {
            topologyWithinMs: 1000,
            topologyEveryMs: 10,
        }).run(shortSmoke(valves, traffic, options), signal)
        results.push(result)
        return result
    }

    const deliveriesOf = (truth: TruthRecord[]): string[] =>
        truth.map(({ unitId, actionId, status }) => `${unitId}/${actionId}/${status}`).sort()

    it.each<[string, Parameters<typeof environmentOf>[0], string, () => void, object, string | undefined]>([
        [
            'passes when the roles deliver every unit and finish every job',
            'all',
            'event_email',
            () => undefined,
            {
                status: 'passed',
                statusReason: 'every invariant held',
                measurements: expect.arrayContaining([
                    expect.objectContaining({ name: 'delivery_latency_ms', key: 'p50', unit: 'ms' }),
                ]),
            },
            'email',
        ],
        [
            'passes when the edge records a webhook delivery for every unit',
            'all',
            'event_webhook',
            () => undefined,
            { status: 'passed', statusReason: 'every invariant held' },
            'webhook',
        ],
        [
            'fails when a job stays unfinished after every unit was delivered',
            'all, leaving one job running',
            'event_email',
            () => undefined,
            { status: 'failed', statusReason: 'not converged: 1 unfinished jobs, 0 units without a delivery record' },
            'email',
        ],
        [
            'fails with the undelivered units when no role delivers',
            'none',
            'event_email',
            () => undefined,
            {
                status: 'failed',
                statusReason: expect.stringMatching(
                    /^not converged: 0 unfinished jobs, [1-9]\d* units without a delivery record; at_least_once failed: [\w-]+-\d+ email: the edge never received it$/
                ),
                invariants: [
                    { name: 'at_least_once', passed: false, observed: expect.any(Number) },
                    { name: 'duplicate_sends', passed: true },
                    { name: 'refused_at_intake', passed: true },
                ],
            },
            undefined,
        ],
        [
            'joins the failed verdict and the producer that did not disconnect',
            'none',
            'event_email',
            failNextDisconnect,
            {
                status: 'invalid',
                statusReason: expect.stringMatching(
                    /^not converged: .*; at_least_once failed: .*; the load producer did not disconnect: Local: Timed out$/
                ),
            },
            undefined,
        ],
    ])(
        '%s',
        async (_story, delivering, traffic, arrange, verdict, deliveredBy) => {
            arrange()

            const result = await run(delivering, [], traffic)

            const offered = (evidenceOf(result, 'journal.json') as JournalEntry[]).filter(
                ({ answer }) => answer.accepted
            )
            expect(result).toMatchObject(verdict)
            expect(evidenceOf(result, 'scorecard.json')).toEqual({
                ...result,
                recorded: undefined,
                captured: undefined,
                scorecardError: undefined,
                host: os.hostname(),
                event: api.captured[0]?.properties,
            })
            expect(api.captured.map(({ properties }) => properties)).toEqual([
                expect.objectContaining({
                    run_id: result.runId,
                    status: result.status,
                    status_reason: result.statusReason,
                }),
            ])
            expect(deliveriesOf(evidenceOf(result, 'truth.json') as TruthRecord[])).toEqual(
                deliveredBy ? offered.map(({ unitId }) => `${unitId}/${deliveredBy}/200`).sort() : []
            )
            expect(offered).not.toHaveLength(0)
            expect(evidenceOf(result, 'topology.json')).toMatchObject({
                hash: result.topologyHash,
                databases: [{ role: 'cdp-cyclotron-worker-hogflow', database: 'cyclotron' }],
                hosts: deliveredBy
                    ? [{ host: deliveredBy === 'email' ? 'ses' : 'hooks.example.com', requests: offered.length }]
                    : [],
            })
            expect(api.captured[0]?.properties.topology_hash).toEqual(expect.stringMatching(/^[0-9a-f]{12}$/))
        },
        30_000
    )
    it.each([
        ['passes a duplicate send the janitor reset accounts for', 1, true],
        ['fails a duplicate send that no janitor reset accounts for', 0, false],
    ])(
        '%s',
        async (_story, resets, passed) => {
            janitor.resetsAfterFirstScrape = resets
            let duplicated = false
            jest.mocked(fetch).mockImplementation(async (url, options) => {
                if (!duplicated && String(url).includes(WEBHOOK_HOST)) {
                    duplicated = true
                    await _fetch(url, options, throughTheEdge)
                }
                return _fetch(url, options, throughTheEdge)
            })

            const result = await run('all', [], 'event_webhook')

            expect(result).toMatchObject({
                status: passed ? 'passed' : 'failed',
                janitorResets: resets,
                invariants: expect.arrayContaining([
                    expect.objectContaining({ name: 'duplicate_sends', passed, observed: 1, gate: 0 }),
                ]),
            })
            expect(api.captured[0]?.properties).toMatchObject({ janitor_resets: resets, inv_duplicate_sends_gate: 0 })
        },
        30_000
    )

    it('fails a run whose intake role refused every unit, rather than calling it invalid', async () => {
        const result = await createRunner(environmentOf('none'), env).run(
            shortSmoke([], 'transactional_email'),
            NEVER_ABORTED
        )
        results.push(result)

        expect(result).toMatchObject({
            status: 'failed',
            statusReason: expect.stringMatching(
                /^refused_at_intake failed: [\w-]+-1: the intake could not be reached: .*ECONNREFUSED/
            ),
            units: { targetUnits: 4, offeredUnits: 4 },
        })
    }, 30_000)

    it('samples every replica the profile starts, follows every sample live, and seeds flows that park as often as it asks', async () => {
        const result = await createRunner(environmentOf('none'), env).run(
            shortSmoke([], 'event_email', { replicas: { 'cdp-cyclotron-worker-email': 2 }, parks: 1 }),
            NEVER_ABORTED
        )
        results.push(result)

        const teams = (evidenceOf(result, 'journal.json') as JournalEntry[]).map(({ teamId }) => teamId)
        const flows = await withPostgres(
            async (client) =>
                (
                    await client.query<{ actions: { type: string }[] }>(
                        'SELECT actions FROM posthog_hogflow WHERE team_id = ANY($1)',
                        [teams]
                    )
                ).rows,
            defaultConfig.DATABASE_URL
        )
        const { samples } = evidenceOf(result, 'metrics.json') as { samples: { role: string; replica: number }[] }
        const followed = readFileSync(path.join(result.evidenceDir, LIVE_FILE), 'utf8')
            .trimEnd()
            .split('\n')
            .map((line) => parseJSON(line) as LiveRecord)
            .flatMap((record) => (record.type === 'tick' ? record.samples : []))
        expect({
            unfollowedSamples: samples.length - followed.length,
            parksPerFlow: [
                ...new Set(flows.map(({ actions }) => actions.filter(({ type }) => type === 'delay').length)),
            ],
            emailReplicas: [
                ...new Set(
                    samples.filter(({ role }) => role === 'cdp-cyclotron-worker-email').map(({ replica }) => replica)
                ),
            ].sort(),
        }).toEqual({ unfollowedSamples: 0, parksPerFlow: [1], emailReplicas: [0, 1] })
    }, 30_000)

    it.each<[string, Parameters<typeof environmentOf>[0], string, string | undefined, string, object]>([
        [
            'passes when the roles finish every job of the run beside the resident backlog',
            'all',
            SMOKE.profile.name,
            undefined,
            'passed',
            { passed: true, observed: 0 },
        ],
        [
            'fails when a resident job seeded before the run is gone after it',
            'all',
            SMOKE.profile.name,
            'DELETE FROM cyclotron_jobs WHERE id = (SELECT id FROM cyclotron_jobs WHERE team_id = $1 LIMIT 1)',
            'failed',
            {
                passed: false,
                violation: `team ${RESIDENT_TEAMS_FROM + 1} hogflow available: expected 2 rows, found 1`,
            },
        ],
        [
            "fails when a resident job's state was cut short after the seed",
            'all',
            SMOKE.profile.name,
            `UPDATE cyclotron_jobs SET state = substring(state FROM 1 FOR 10)
             WHERE id = (SELECT id FROM cyclotron_jobs WHERE team_id = $1 LIMIT 1)`,
            'failed',
            {
                passed: false,
                violation: expect.stringMatching(
                    new RegExp(`^team ${RESIDENT_TEAMS_FROM + 1} hogflow available: the rows changed in place`)
                ),
            },
        ],
        [
            'fails when the backlog was seeded for another profile',
            'all',
            'another',
            undefined,
            'failed',
            {
                passed: false,
                violation: `the resident backlog was seeded for profile another; run seed-backlog with profile ${SMOKE.profile.name} first`,
            },
        ],
    ])(
        'resident_backlog_intact %s',
        async (_story, delivering, seededFor, tamper, status, expected) => {
            const backlog: Backlog = {
                teams: 2,
                jobs: { hogflow: 4 },
                stateBytes: { p50: 100, p90: 200, p99: 300 },
                compressibility: 0.5,
                parkFor: '10080m',
                tolerance: 0,
            }
            const seeded = await seedBacklog(seededFor, backlog, cyclotronUrl, defaultStateDir(env))
            expect(seeded.manifest).toBeDefined()
            if (tamper !== undefined) {
                await withPostgres((client) => client.query(tamper, [RESIDENT_TEAMS_FROM + 1]), cyclotronUrl)
            }

            const result = await createRunner(environmentOf(delivering), env).run(
                shortSmoke([], 'event_email', {
                    invariants: [{ name: 'resident_backlog_intact', params: {} }],
                    backlog,
                }),
                NEVER_ABORTED
            )
            results.push(result)

            expect(result).toMatchObject({
                status,
                invariants: [expect.objectContaining({ name: 'resident_backlog_intact', ...expected })],
            })
        },
        30_000
    )

    const KILL_EMAIL_WORKER: ValveEntry = {
        valve: 'role.kill',
        target: 'cdp-cyclotron-worker-email',
        dose: {},
        at: '0s',
        for: '1s',
    }

    it.each<[string, (role: Role) => RoleExit[], object, Parameters<typeof shortSmoke>[2]]>([
        ['passes a run whose only exit is the kill its card scheduled', exitOfTheKill, { status: 'passed' }, {}],
        [
            'calls a run invalid whose valve left too short a baseline to admit its load, and measures the kill',
            exitOfTheKill,
            {
                status: 'invalid',
                statusReason: expect.stringMatching(
                    /^the load admission failed: the baseline was too short to measure: /
                ),
                admissions: [
                    {
                        name: 'load',
                        passed: false,
                        reason: expect.stringMatching(
                            /^the baseline was too short to measure: [0-9.]+s, under the 30s minimum$/
                        ),
                    },
                ],
                measurements: [{ name: 'pg_client_errors', unit: 'errors', value: 0 }],
            },
            {
                measures: [{ name: 'pg_client_errors', params: {} }],
                load: { targets: { claimsPerSecond: { email: 500 } }, tolerance: 0.1 },
            },
        ],
        [
            'fails a run in which a role exits that no valve killed',
            () => [
                {
                    role: 'cdp-cyclotron-worker-hogflow',
                    replica: 0,
                    at: new Date().toISOString(),
                    code: 1,
                    signal: null,
                    byValve: false,
                },
            ],
            {
                status: 'failed',
                statusReason: 'cdp-cyclotron-worker-hogflow exited (code 1) without a valve causing it',
            },
            {},
        ],
    ])(
        '%s, and keeps the valve timeline',
        async (_story, exitsOfKill, verdict, options) => {
            killExits = exitsOfKill

            const result = await run('all', [{ ...KILL_EMAIL_WORKER, at: '1s', for: '500ms' }], undefined, options)

            expect(result).toMatchObject({
                ...verdict,
                timeline: [
                    {
                        valve: 'role.kill',
                        target: 'cdp-cyclotron-worker-email',
                        observedAt: expect.any(String),
                        releasedAt: expect.any(String),
                    },
                ],
            })
            expect(api.captured[0]?.properties.valve_timeline).toEqual(result.timeline)
            expect(api.captured[0]?.properties.admissions).toEqual(result.admissions)
            expect(evidenceOf(result, 'probes.json')).toEqual({
                drive: { startedAt: expect.any(Number), endedAt: expect.any(Number) },
                writer: expect.arrayContaining([expect.objectContaining({ ok: true, inRecovery: false })]),
                queue: expect.arrayContaining([expect.objectContaining({ due: expect.any(Number) })]),
            })
        },
        30_000
    )

    it('fails a run in which a role exits while its topology settles', async () => {
        exitsAtWiringRead = [
            {
                role: 'cdp-cyclotron-worker-hogflow',
                replica: 0,
                at: new Date().toISOString(),
                code: 1,
                signal: null,
                byValve: false,
            },
        ]

        const result = await run('all')

        expect(result).toMatchObject({
            status: 'failed',
            statusReason: 'cdp-cyclotron-worker-hogflow exited (code 1) without a valve causing it',
        })
    }, 30_000)

    it('drives a run whose topology still changes at the deadline, and records a read past the first two', async () => {
        wiringChurns = true

        const result = await run('all')

        const [recorded] = (evidenceOf(result, 'topology.json') as Wiring).databases
        expect({
            status: result.status,
            recordedPastTheFirstTwoReads: Number(recorded.database.replace('cyclotron-', '')) >= 2,
        }).toEqual({ status: 'passed', recordedPastTheFirstTwoReads: true })
    }, 30_000)

    it('calls a run invalid before its drive when it is interrupted during a topology read that never answers', async () => {
        const interrupt = new AbortController()
        interruptAtWiringRead = { read: 1, interrupt }
        hangsFromWiringRead = 1
        const result = await run('all', [KILL_EMAIL_WORKER], undefined, {}, interrupt.signal)

        expect(result).toMatchObject({
            status: 'invalid',
            statusReason: 'the run stopped: the run was interrupted while it read its topology',
            timeline: [],
        })
    }, 30_000)

    it('drives a run whose topology read still hangs at the deadline, and records the read before it', async () => {
        wiringChurns = true
        hangsFromWiringRead = 2

        const result = await run('all')

        expect({
            status: result.status,
            databases: (evidenceOf(result, 'topology.json') as Wiring).databases.map(({ database }) => database),
        }).toEqual({ status: 'passed', databases: ['cyclotron-1'] })
    }, 30_000)

    it('calls a run invalid before its drive when a valve targets a node its topology lacks, and names the nodes found', async () => {
        cyclotronJoinsAtRead = Infinity
        const [failover] = load(path.join(__dirname, '..', 'cards', 'cyclotron-failover-under-load.yaml')).card.valves

        const result = await run('all', [{ ...failover, at: '1s', for: '500ms' }])

        expect(result).toMatchObject({
            status: 'invalid',
            statusReason:
                "the run stopped: the card targets cyclotron, which this run's topology does not have; it found cdp-api, cdp-cyclotron-v2-janitor, cdp-cyclotron-worker-email, cdp-cyclotron-worker-hogflow, cdp-processed-events, cdp-ses-webhooks, ses, hooks.example.com",
            timeline: [],
        })
        expect(api.captured[0]?.properties.topology_hash).toEqual(result.topologyHash)
    }, 30_000)

    it.each([
        ['a database client that joined late', { failed: 0, joinsAt: 2, groupsJoinAt: 0 }],
        ['a read that failed', { failed: 1, joinsAt: 0, groupsJoinAt: 0 }],
        ['a consumer group that joined late', { failed: 0, joinsAt: 0, groupsJoinAt: 3 }],
    ])(
        'reads the topology again past %s, and runs the card',
        async (_case, { failed, joinsAt, groupsJoinAt }) => {
            failedWiringReads = failed
            cyclotronJoinsAtRead = joinsAt
            groupsJoinAtRead = groupsJoinAt
            const [failover] = load(path.join(__dirname, '..', 'cards', 'cyclotron-failover-under-load.yaml')).card
                .valves

            const result = await run('all', [{ ...failover, at: '1s', for: '500ms' }])

            expect({
                statusReason: result.statusReason,
                consumers: (evidenceOf(result, 'topology.json') as Wiring).consumers.length,
            }).toEqual({
                statusReason: 'pg.failover on cyclotron was not observed: pg.failover runs only on a run host',
                consumers: consumerGroupsOf(handles).length,
            })
        },
        30_000
    )

    it('calls the failover card invalid at its valve on a host without a run manifest', async () => {
        const [failover] = load(path.join(__dirname, '..', 'cards', 'cyclotron-failover-under-load.yaml')).card.valves

        const result = await run('all', [{ ...failover, at: '1s', for: '500ms' }])

        expect(result).toMatchObject({
            status: 'invalid',
            statusReason: 'pg.failover on cyclotron was not observed: pg.failover runs only on a run host',
            timeline: [{ valve: 'pg.failover', target: 'cyclotron', error: 'pg.failover runs only on a run host' }],
        })
    }, 30_000)

    it('calls the failover card invalid before its promote when its valve refuses a malformed capacity read', async () => {
        const [failover] = load(path.join(__dirname, '..', 'cards', 'cyclotron-failover-under-load.yaml')).card.valves
        pinClockAfterMinuteStart()
        const cloud = new FakeCloud({
            now: () => new Date(),
            failover: { takesMs: 20 },
            liveReaderAcu: { maxima: [1, 1, 1, 1, 1] },
            shortValuesOf: 'Maximum',
        })
        const { manifest } = cloud.runCluster(randomUUID())
        const manifestFile = path.join(cacheHome, 'manifest.json')
        writeFileSync(manifestFile, JSON.stringify({ ...manifest, schedules: [] }))
        const host = createEnvironment({
            aws: cloud,
            failover: {
                identity: () => Promise.resolve({ instance: cloud.writerOf(manifest.stackName)!, inRecovery: false }),
            },
        })
        const onHost: Environment = { ...environmentOf('all'), actuate: (action) => host.actuate(action) }

        const result = await createRunner(
            onHost,
            { ...env, SCENARIO_RUN_MANIFEST: manifestFile },
            {
                topologyWithinMs: 1000,
                topologyEveryMs: 10,
            }
        ).run(shortSmoke([{ ...failover, at: '1s', for: '500ms' }]), NEVER_ABORTED)
        results.push(result)

        const refusal = expect.stringMatching(
            /^pg\.failover refused: .*-reader's capacity read has \d+ timestamps and \d+ values/
        )
        expect(result).toMatchObject({
            status: 'invalid',
            statusReason: expect.stringMatching(/^pg\.failover on cyclotron was not observed: pg\.failover refused: /),
            timeline: [{ valve: 'pg.failover', target: 'cyclotron', error: refusal }],
        })
        expect(result.timeline[0]).not.toHaveProperty('intentAt')
        expect(cloud.promotions).toEqual([])
        expect(cloud.writerOf(manifest.stackName)).toBe(`${manifest.stackName}-writer`)
    }, 30_000)

    it('calls the scale card invalid at its writer CPU bar on a host without a run manifest', async () => {
        const { bars } = load(path.join(__dirname, '..', 'cards', 'cyclotron-scale.yaml')).card
        const ramp = [
            { scale: 1, for: '1s' },
            { scale: 2, for: '1s' },
        ]

        const result = await run('all', [], undefined, { ramp, bars })

        expect(result.status).toBe('invalid')
        expect(result.bars[0]).toEqual({
            name: 'writer_cpu_under',
            unit: '%',
            limit: 70,
            passed: false,
            unjudged: 'no writer CPU reading off a run host in the 1x step',
            harnessLimit: expect.objectContaining({ by: 'run_host', scale: 1 }),
        })
    }, 30_000)

    it('leaves a valve due after the drive window unapplied while an intake answer is still pending', async () => {
        const slowIntake = http.createServer((_request, response) => {
            setTimeout(() => response.writeHead(503).end(), 3_000)
        })
        await new Promise<void>((resolve) => slowIntake.listen(0, '127.0.0.1', resolve))
        try {
            const result = await createRunner(
                environmentOf('none', `http://127.0.0.1:${(slowIntake.address() as AddressInfo).port}`),
                env
            ).run(shortSmoke([{ ...KILL_EMAIL_WORKER, at: '2500ms' }], 'transactional_email'), NEVER_ABORTED)
            results.push(result)

            expect(result.timeline).toEqual([
                {
                    valve: 'role.kill',
                    target: 'cdp-cyclotron-worker-email',
                    requestedAt: expect.any(String),
                    error: 'never applied: released before its offset',
                },
            ])
            expect(exits).toEqual([])
        } finally {
            slowIntake.closeAllConnections()
            await new Promise((resolve) => slowIntake.close(resolve))
        }
    }, 30_000)
})
