import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { Code, ConnectError, ConnectRouter } from '@connectrpc/connect'
import { connectNodeAdapter } from '@connectrpc/connect-node'
import { randomUUID } from 'crypto'
import { Http2Server, ServerHttp2Session, createServer as createHttp2Server } from 'http2'
import { AddressInfo } from 'net'
import { AdminClient, Message, Metadata, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'
import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { KafkaConsumerV2 } from '~/common/kafka/consumer/consumer-v2'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogClient } from '~/common/personhog/client'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../../_tests/examples'
import { createHogExecutionGlobals, insertHogFunction } from '../../_tests/fixtures'
import { createCdpCoreServices } from '../../cdp-services'
import { CdpConsumerBaseDeps } from '../../consumers/cdp-base.consumer'
import {
    CdpCyclotronDeadLetterWorker,
    SKIPPED_FUNCTION_DISABLED_ERROR_KIND,
} from '../../consumers/cdp-cyclotron-dead-letter-worker.consumer'
import { CdpCyclotronWorker } from '../../consumers/cdp-cyclotron-worker.consumer'
import { CdpEventsConsumer } from '../../consumers/cdp-events.consumer'
import {
    CdpProducerName,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '../../outputs/producers'
import { CyclotronJobInvocation, CyclotronJobQueueKind, DEAD_LETTER_QUEUE, HogFunctionType } from '../../types'
import { CyclotronJobQueueKafka, serializeInvocation } from '../job-queue/job-queue-kafka'
import { HogWatcherState } from '../monitoring/hog-watcher.service'
import { CrashGuard, CrashGuardSettings, batchAttemptsKey, createCrashGuardSettings } from './crash-guard'
import { divertToDeadLetter } from './divert-to-dead-letter'
import { QUARANTINED_ERROR_KIND } from './quarantine-invocations'

jest.mock('~/common/utils/posthog', () => ({
    ...jest.requireActual('~/common/utils/posthog'),
    captureTeamEvent: jest.fn(),
}))

const mockCaptureTeamEvent: jest.Mock = require('~/common/utils/posthog').captureTeamEvent

const MAX_ATTEMPTS = 2
const DIVERT_TOPIC = `cdp_cyclotron_${DEAD_LETTER_QUEUE}`

type ConsumeBatch = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<unknown> }>

describe('CDP batch quarantine against Kafka and Valkey', () => {
    jest.setTimeout(120_000)

    const usedV2 = defaultConfig.CONSUMER_USE_V2
    let producer: KafkaProducerWrapper
    let kind: CyclotronJobQueueKind
    let topic: string
    let group: string
    let workers: CyclotronJobQueueKafka[]
    let processed: string[]
    let poison: { key: string; value: string; headers: Record<string, string> }

    beforeAll(async () => {
        defaultConfig.CONSUMER_USE_V2 = true
        producer = await KafkaProducerWrapper.create(undefined)
    })

    afterAll(async () => {
        defaultConfig.CONSUMER_USE_V2 = usedV2
        await producer.disconnect()
    })

    beforeEach(async () => {
        // The worker reads cdp_cyclotron_<queue> as group cdp-cyclotron-<queue>-consumer. A queue name of
        // its own gives each test a fresh topic and group, so nothing a previous run left behind is read.
        kind = `batch_quarantine_e2e_${randomUUID().replace(/-/g, '')}` as CyclotronJobQueueKind
        topic = `cdp_cyclotron_${kind}`
        group = `cdp-cyclotron-${kind}-consumer`
        workers = []
        processed = []
        poison = { key: randomUUID(), value: 'not-json', headers: { teamId: '2', functionId: 'poisoned-fn' } }
        await ensureKafkaTopics([topic, DIVERT_TOPIC])
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await Promise.all(workers.map(stopWorker))
        await deleteKafkaTopics([topic])
    })

    const quarantineFor = (mode: CrashGuardSettings['mode']): CrashGuardSettings =>
        createCrashGuardSettings({
            ...defaultConfig,
            CDP_BATCH_QUARANTINE_MODE: mode,
            CDP_BATCH_QUARANTINE_MAX_ATTEMPTS: MAX_ATTEMPTS,
            CDP_BATCH_QUARANTINE_KEY_TTL_SECONDS: 300,
        })!

    const recordProcessed: ConsumeBatch = (invocations) => {
        processed.push(...invocations.map((invocation) => invocation.id))
        return Promise.resolve({ backgroundTask: Promise.resolve() })
    }

    const startWorker = async (
        quarantine: CrashGuardSettings,
        consumeBatch: ConsumeBatch = recordProcessed
    ): Promise<CyclotronJobQueueKafka> => {
        const worker = new CyclotronJobQueueKafka(undefined, defaultConfig, defaultConfig.CONSUMER_BATCH_SIZE)
        workers.push(worker)
        await worker.startAsProducer()
        await worker.startAsConsumer(kind, consumeBatch, {
            crashGuard: ({ groupId, produce }) =>
                new CrashGuard(quarantine, groupId, divertToDeadLetter(produce, groupId)),
        })
        return worker
    }

    const stopWorker = async (worker: CyclotronJobQueueKafka): Promise<void> => {
        workers = workers.filter((x) => x !== worker)
        await worker.stopConsumer()
        await worker.stopProducer()
    }

    const crashOf = async (worker: CyclotronJobQueueKafka): Promise<unknown> => {
        const consumer = worker['kafkaConsumer']
        const loop: Promise<void> =
            consumer instanceof KafkaConsumerV2 ? consumer['loopDone']! : (consumer as KafkaConsumer)['consumerLoop']!
        let crash: unknown
        loop.catch((error) => {
            crash = error
        })
        await waitForExpect(() => expect(crash).toBeDefined(), 30_000)
        return crash
    }

    const crashLoop = async (
        quarantine: CrashGuardSettings,
        restarts: number,
        consumeBatch?: ConsumeBatch
    ): Promise<unknown[]> => {
        const crashes: unknown[] = []
        for (let i = 0; i < restarts; i++) {
            const worker = await startWorker(quarantine, consumeBatch)
            crashes.push(await crashOf(worker))
            await stopWorker(worker)
        }
        return crashes
    }

    type TestMessage = { key: string; value: string; headers?: Record<string, string>; partition?: number }

    const produce = (message: TestMessage): Promise<void> =>
        producer.produce({ topic, ...message, value: Buffer.from(message.value) })

    const invocation = (id: string): string =>
        JSON.stringify({ id, teamId: 2, functionId: 'healthy-fn', state: {}, queue: kind, queuePriority: 0 })

    const produceInvocation = async (partition?: number): Promise<string> => {
        const id = randomUUID()
        await produce({ key: id, value: invocation(id), partition })
        return id
    }

    // Reads the whole dead letter topic up to its current end, so an empty result means nothing was diverted.
    const divertedWithKey = async (key: string): Promise<Message[]> => {
        const reader = new KafkaConsumerV2({
            groupId: `batch-quarantine-e2e-read-${randomUUID()}`,
            topic: DIVERT_TOPIC,
            autoCommit: false,
            batchTimeoutMs: 50,
        })
        const read: Message[] = []
        await reader.connect((batch) => {
            read.push(...batch)
            return Promise.resolve()
        })
        try {
            const partitions = await reader.getPartitionsForTopic(DIVERT_TOPIC)
            const ends = await Promise.all(
                partitions.map(async ({ id }) => ({
                    id,
                    end: (await reader.queryWatermarkOffsets(DIVERT_TOPIC, id))[1],
                }))
            )
            await waitForExpect(() => {
                for (const { id, end } of ends.filter((x) => x.end > 0)) {
                    expect(read.some((m) => m.partition === id && m.offset >= end - 1)).toBe(true)
                }
            }, 30_000)
        } finally {
            await reader.disconnect()
        }
        return read.filter((m) => m.key?.toString() === key)
    }

    const counter = async (name: string, labels: Record<string, string> = {}): Promise<number> =>
        (await register.getSingleMetric(name)!.get()).values.find((v) =>
            Object.entries(labels).every(([k, value]) => v.labels[k] === value)
        )?.value ?? 0

    const storedAttempts = (
        quarantine: CrashGuardSettings,
        partition: number,
        offset: number
    ): Promise<string | null> =>
        quarantine.valkey.useClient({ name: 'test' }, (client) =>
            client.hget(batchAttemptsKey(group, partition, offset), 'attempts')
        )

    const growTopic = async (partitions: number): Promise<void> => {
        const admin = AdminClient.create({
            'client.id': 'batch-quarantine-e2e',
            'metadata.broker.list': defaultConfig.KAFKA_HOSTS,
        })
        try {
            await new Promise<void>((resolve, reject) =>
                admin.createPartitions(topic, partitions, 10_000, (error) => (error ? reject(error) : resolve()))
            )
        } finally {
            admin.disconnect()
        }
    }

    const asDiverted = (messages: Message[]): { value: string; headers: Record<string, string> }[] =>
        messages.map((m) => ({ value: m.value!.toString(), headers: parseKafkaHeaders(m.headers) }))

    it('diverts a batch that crashed the worker too often, then moves on and commits past it', async () => {
        const quarantine = quarantineFor('enforce')
        await produce(poison)

        expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))

        let worker = await startWorker(quarantine)
        await waitForExpect(
            async () => expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1),
            30_000
        )
        expect(asDiverted(await divertedWithKey(poison.key))).toEqual([
            { value: poison.value, headers: poison.headers },
        ])

        const healthy = await produceInvocation()
        await waitForExpect(() => expect(processed).toEqual([healthy]), 30_000)
        await stopWorker(worker)

        // Something new to wait for, because a restart that replays nothing is otherwise indistinguishable
        // from one that has not fetched yet.
        worker = await startWorker(quarantine)
        const later = await produceInvocation()
        await waitForExpect(() => expect(processed).toEqual([healthy, later]), 30_000)

        expect(await divertedWithKey(poison.key)).toHaveLength(1)
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(1)
        expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1)
        expect(await storedAttempts(quarantine, 0, 0)).toEqual(String(MAX_ATTEMPTS + 1))
    })

    it.each([
        ['v1', false],
        ['v2', true],
    ])('keeps crashing on the batch while the divert fails, with consumer %s', async (_, useV2) => {
        const configuredV2 = defaultConfig.CONSUMER_USE_V2
        defaultConfig.CONSUMER_USE_V2 = useV2
        try {
            const quarantine = quarantineFor('enforce')
            await produce(poison)
            expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))

            const dlqDown = new Error('hogdlq unavailable')
            const produceToKafka = KafkaProducerWrapper.prototype.produce
            const failDivert = jest.spyOn(KafkaProducerWrapper.prototype, 'produce').mockImplementation(function (
                this: KafkaProducerWrapper,
                message
            ) {
                return message.topic === DIVERT_TOPIC ? Promise.reject(dlqDown) : produceToKafka.call(this, message)
            })
            expect(await crashLoop(quarantine, 2)).toEqual([dlqDown, dlqDown])
            failDivert.mockRestore()

            await startWorker(quarantine)
            await waitForExpect(
                async () => expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1),
                30_000
            )
            const healthy = await produceInvocation()
            await waitForExpect(() => expect(processed).toEqual([healthy]), 30_000)

            expect(asDiverted(await divertedWithKey(poison.key))).toEqual([
                { value: poison.value, headers: poison.headers },
            ])
            // Each restart counts one more attempt at offset 0, so a failed divert never moved the commit past it.
            expect(await storedAttempts(quarantine, 0, 0)).toEqual(String(MAX_ATTEMPTS + 3))
        } finally {
            defaultConfig.CONSUMER_USE_V2 = configuredV2
        }
    })

    it.each([
        ['v1', false],
        ['v2', true],
    ])(
        'takes back the attempt of a background task that outlives the guard timeout, with consumer %s',
        async (_, useV2) => {
            const configured = {
                useV2: defaultConfig.CONSUMER_USE_V2,
                timeoutMs: defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS,
            }
            defaultConfig.CONSUMER_USE_V2 = useV2
            // The guard gives up 2s earlier, after twice the 500ms Valkey timeout and a 1s margin.
            defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS = 4_000
            try {
                const quarantine = quarantineFor('enforce')
                const id = await produceInvocation()
                // A produce that librdkafka keeps retrying through a Kafka outage holds the background task. In
                // production consumer v2 exits the process on the timeout, so the task never finishes and no
                // success clears the count. The test cannot kill the process, so with v2 the task fails instead.
                const stalled: ConsumeBatch = (invocations) => {
                    if (invocations.length === 0) {
                        return recordProcessed(invocations)
                    }
                    processed.push(...invocations.map((invocation) => invocation.id))
                    const backgroundTask = new Promise((resolve, reject) =>
                        setTimeout(() => (useV2 ? reject(new Error('process exited')) : resolve(undefined)), 6_000)
                    )
                    return Promise.resolve({ backgroundTask })
                }

                if (useV2) {
                    // Consumer v2 gives up on the task and restarts, which reads as a crash without the take back.
                    const crashes = await crashLoop(quarantine, MAX_ATTEMPTS + 1, stalled)
                    expect(crashes).toEqual(
                        Array(MAX_ATTEMPTS + 1).fill(
                            expect.objectContaining({ message: 'background_task_timeout_after_4000ms' })
                        )
                    )
                    expect(await storedAttempts(quarantine, 0, 0)).toEqual('0')
                } else {
                    // Consumer v1 waits for the task, so the take back leaves the batch running and clears the count once it finishes.
                    await startWorker(quarantine, stalled)
                    await waitForExpect(
                        async () => expect(await counter('cdp_batch_attempts_uncounted_total', { group })).toEqual(1),
                        30_000
                    )
                    expect(await storedAttempts(quarantine, 0, 0)).toEqual('0')
                    await waitForExpect(async () => expect(await storedAttempts(quarantine, 0, 0)).toBeNull(), 30_000)
                }
                expect(processed).toEqual(Array(useV2 ? MAX_ATTEMPTS + 1 : 1).fill(id))
                expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(0)
            } finally {
                defaultConfig.CONSUMER_USE_V2 = configured.useV2
                defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS = configured.timeoutMs
            }
        }
    )

    it('diverts a healthy partition together with the poisoned partition it was fetched with', async () => {
        await growTopic(2)
        const quarantine = quarantineFor('enforce')
        const healthyId = randomUUID()
        const healthy = {
            key: healthyId,
            value: invocation(healthyId),
            headers: { teamId: '2', functionId: 'healthy-fn' },
        }
        await produce({ ...poison, partition: 0 })
        await produce({ ...healthy, partition: 1 })

        expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))
        // A count on partition 1 means each crashing fetch held both partitions. Had partition 1 come in a
        // fetch of its own, it would have been processed and its count cleared, or never been fetched at all.
        expect(await storedAttempts(quarantine, 1, 0)).toEqual(String(MAX_ATTEMPTS))

        await startWorker(quarantine)
        await waitForExpect(
            async () => expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(2),
            30_000
        )
        const later = [await produceInvocation(0), await produceInvocation(1)]
        await waitForExpect(() => expect([...processed].sort()).toEqual([...later].sort()), 30_000)

        expect(asDiverted(await divertedWithKey(healthyId))).toEqual([
            { value: healthy.value, headers: healthy.headers },
        ])
        expect(await divertedWithKey(poison.key)).toHaveLength(1)
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(2)
    })

    it('diverts a batch once when the worker crashes after the divert and before the commit', async () => {
        await growTopic(2)
        const quarantine = quarantineFor('enforce')
        await produce({ ...poison, partition: 0 })
        expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))
        const healthy = await produceInvocation(1)

        const crashAfterDivert = new Error('worker crashed after the divert')
        let crashed = false
        const crashOnce: ConsumeBatch = (invocations) => {
            if (!crashed && invocations.length > 0) {
                crashed = true
                return Promise.reject(crashAfterDivert)
            }
            return recordProcessed(invocations)
        }
        expect(await crashLoop(quarantine, 1, crashOnce)).toEqual([crashAfterDivert])
        await startWorker(quarantine)
        await waitForExpect(() => expect(processed).toEqual([healthy]), 30_000)

        // Two flags on offset 0 mean the crash replayed the fetch that diverted the poison.
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(2)
        expect(await divertedWithKey(poison.key)).toHaveLength(1)
        expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1)
    })

    it('keeps crashing on the batch in shadow mode and diverts nothing', async () => {
        const quarantine = quarantineFor('shadow')
        await produce(poison)

        const crashes = await crashLoop(quarantine, MAX_ATTEMPTS + 1)

        expect(crashes).toEqual(Array(MAX_ATTEMPTS + 1).fill(expect.any(SyntaxError)))
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'shadow' })).toEqual(1)
        expect(await divertedWithKey(poison.key)).toEqual([])
    })

    it('does not divert a batch that only failed while a dependency was down', async () => {
        const quarantine = quarantineFor('enforce')
        const id = await produceInvocation()
        let dependencyDown = true
        const consumeBatch: ConsumeBatch = (invocations) => {
            if (dependencyDown && invocations.length > 0) {
                return Promise.reject(
                    new DependencyUnavailableError('personhog unavailable', 'personhog', new Error('ECONNREFUSED'))
                )
            }
            return recordProcessed(invocations)
        }

        const crashes = await crashLoop(quarantine, MAX_ATTEMPTS + 1, consumeBatch)
        expect(crashes).toEqual(Array(MAX_ATTEMPTS + 1).fill(expect.any(DependencyUnavailableError)))
        expect(Number(await storedAttempts(quarantine, 0, 0))).toBeLessThanOrEqual(MAX_ATTEMPTS)

        dependencyDown = false
        await startWorker(quarantine, consumeBatch)

        await waitForExpect(() => expect(processed).toEqual([id]), 30_000)
        expect(await divertedWithKey(id)).toEqual([])
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(0)
    })

    describe('through the hog and dead letter workers', () => {
        const usedBatchSize = defaultConfig.CONSUMER_BATCH_SIZE
        const HOG_TOPIC = 'cdp_cyclotron_hog'
        const HOG_GROUP = 'cdp-cyclotron-hog-consumer'
        const DLQ_GROUP = `cdp-cyclotron-${DEAD_LETTER_QUEUE}-consumer`
        let hub: Hub
        let team: Team
        let poisonFn: HogFunctionType
        let healthyFn: HogFunctionType
        let cdpWorkers: CdpCyclotronWorker[]
        let results: KafkaProducerObserver
        let personsDown: boolean
        let personhogServer: Http2Server
        let personhogSessions: ServerHttp2Session[]
        let personhogClient: PersonHogClient
        let hogStart: number
        let watchers: ReturnType<typeof createCdpCoreServices>

        beforeAll(async () => {
            // Personhog is the dependency every hog function invocation without a person waits on. This stub
            // answers over gRPC, so the real client, its retries and its error tagging all run.
            personhogSessions = []
            personhogServer = createHttp2Server(
                connectNodeAdapter({
                    routes: (router: ConnectRouter) => {
                        router.service(PersonHogService, {
                            getPersonsByDistinctIds: () => {
                                if (personsDown) {
                                    throw new ConnectError('personhog unavailable', Code.Unavailable)
                                }
                                return {}
                            },
                        })
                    },
                })
            )
            personhogServer.on('session', (session) => personhogSessions.push(session))
            await new Promise<void>((resolve) => personhogServer.listen(0, '127.0.0.1', resolve))
            personhogClient = PersonHogClient.fromConfig({
                addr: `127.0.0.1:${(personhogServer.address() as AddressInfo).port}`,
                clientName: 'batch-quarantine-e2e',
            })
        })

        afterAll(async () => {
            defaultConfig.CONSUMER_BATCH_SIZE = usedBatchSize
            personhogClient.close()
            personhogSessions.forEach((session) => session.destroy())
            await new Promise<void>((resolve) => personhogServer.close(() => resolve()))
        })

        beforeEach(async () => {
            await ensureKafkaTopics([...TEST_KAFKA_TOPICS, KAFKA_HOG_INVOCATION_RESULTS, HOG_TOPIC])
            await resetTestDatabase()
            hub = await createHub({ HOG_INVOCATION_RESULTS_ENABLED: true })
            team = await getFirstTeam(hub.postgres)
            cdpWorkers = []
            personsDown = false
            results = new KafkaProducerObserver(producer)
            mockCaptureTeamEvent.mockClear()
            poisonFn = await insertFunction()
            healthyFn = await insertFunction()
            await skipBacklog(DIVERT_TOPIC, DLQ_GROUP)
            hogStart = await skipBacklog(HOG_TOPIC, HOG_GROUP)
            watchers = createCdpCoreServices(hub, deps())
        })

        afterEach(async () => {
            await Promise.all(cdpWorkers.map(stopCdpWorker))
            // cdp_cyclotron_hog is shared with other suites, so nothing this test left there may reach them.
            await skipBacklog(HOG_TOPIC, HOG_GROUP)
            await closeHub(hub)
        })

        const insertFunction = (): Promise<HogFunctionType> =>
            insertHogFunction(hub.postgres, team.id, {
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

        // The topics and groups are shared with every earlier run, so a worker starts past them. Returns the
        // offset the next message on partition 0 gets.
        const skipBacklog = async (topic: string, groupId: string): Promise<number> => {
            const consumer = new RdKafkaConsumer(
                {
                    'group.id': groupId,
                    'metadata.broker.list': defaultConfig.KAFKA_HOSTS,
                    'enable.auto.commit': false,
                },
                {}
            )
            await new Promise<void>((resolve, reject) =>
                consumer.connect({}, (error) => (error ? reject(error) : resolve()))
            )
            try {
                const metadata = await new Promise<Metadata>((resolve, reject) =>
                    consumer.getMetadata({ topic }, (error, data) => (error ? reject(error) : resolve(data)))
                )
                const partitions = metadata.topics.find((x) => x.name === topic)!.partitions
                const ends = await Promise.all(
                    partitions.map(
                        ({ id }) =>
                            new Promise<{ topic: string; partition: number; offset: number }>((resolve, reject) =>
                                consumer.queryWatermarkOffsets(topic, id, 10_000, (error, offsets) =>
                                    error
                                        ? reject(error)
                                        : resolve({ topic, partition: id, offset: offsets.highOffset })
                                )
                            )
                    )
                )
                consumer.commitSync(ends)
                return ends.find((x) => x.partition === 0)!.offset
            } finally {
                await new Promise<void>((resolve) => consumer.disconnect(() => resolve()))
            }
        }

        const deps = (): CdpConsumerBaseDeps => ({
            postgres: hub.postgres,
            pubSub: hub.pubSub,
            encryptedFields: hub.encryptedFields,
            teamManager: hub.teamManager,
            integrationManager: hub.integrationManager,
            cdpProducerRegistry: new KafkaProducerRegistry<CdpProducerName>({
                [WARPSTREAM_INGESTION_PRODUCER]: producer,
                [WARPSTREAM_CYCLOTRON_PRODUCER]: producer,
                [WAREHOUSE_PRODUCER]: producer,
            }),
            internalCaptureService: new InternalCaptureService(hub),
            personRepository: new PersonHogPersonReadRepository(personhogClient, 'batch-quarantine-e2e'),
            geoipService: hub.geoipService,
            groupRepository: {
                fetchGroupsByKeys: () => Promise.resolve([]),
                fetchGroupTypesByTeamIds: () => Promise.resolve({}),
                fetchGroupTypesByProjectIds: () => Promise.resolve({}),
            },
            quotaLimiting: hub.quotaLimiting,
            emailValidationValkey: null,
            frequencyCapValkey: null,
        })

        const startCdpWorker = async (queue: 'hog' | typeof DEAD_LETTER_QUEUE): Promise<CdpCyclotronWorker> => {
            // The dead letter worker runs in shadow mode, because it quarantines in shadow mode too.
            const crashGuardSettings = quarantineFor(queue === DEAD_LETTER_QUEUE ? 'shadow' : 'enforce')
            const jobQueue = new CyclotronJobQueueKafka(undefined, hub, 1)
            const worker =
                queue === DEAD_LETTER_QUEUE
                    ? new CdpCyclotronDeadLetterWorker(hub, { ...deps(), crashGuardSettings }, jobQueue)
                    : new CdpCyclotronWorker(hub, { ...deps(), crashGuardSettings }, jobQueue, queue)
            cdpWorkers.push(worker)
            // The hog worker reads one message per batch here, so each poison is diverted on its own. The dead
            // letter worker keeps the default, because it must read one message per batch by itself.
            defaultConfig.CONSUMER_BATCH_SIZE = queue === 'hog' ? 1 : usedBatchSize
            await worker.start()
            return worker
        }

        const stopCdpWorker = async (worker: CdpCyclotronWorker): Promise<void> => {
            cdpWorkers = cdpWorkers.filter((x) => x !== worker)
            await worker.stop()
        }

        const cdpCrashLoop = async (queue: 'hog' | typeof DEAD_LETTER_QUEUE, restarts: number): Promise<unknown[]> => {
            const crashes: unknown[] = []
            for (let i = 0; i < restarts; i++) {
                const worker = await startCdpWorker(queue)
                crashes.push(await crashOf(worker['cyclotronJobQueue'] as CyclotronJobQueueKafka))
                await stopCdpWorker(worker)
            }
            return crashes
        }

        const startDlqWorker = () => startCdpWorker(DEAD_LETTER_QUEUE)
        const dlqCrashLoop = (restarts: number) => cdpCrashLoop(DEAD_LETTER_QUEUE, restarts)

        const healthyInvocation = (options: { withPerson: boolean } = { withPerson: true }): CyclotronJobInvocation => {
            const globals = createHogExecutionGlobals({
                project: { id: team.id, name: team.name, url: 'http://localhost:8000/project/1' },
            })
            if (!options.withPerson) {
                delete (globals as Partial<typeof globals>).person
            }
            return {
                id: randomUUID(),
                teamId: team.id,
                functionId: healthyFn.id,
                state: { globals, timings: [], attempts: 0 },
                queue: 'hog',
                queuePriority: 0,
            }
        }

        // The worker reads the function and then the state, and nothing guards a missing state, so the
        // invocation throws out of the batch the way a real poison does.
        const poisonedInvocation = (fn: HogFunctionType = poisonFn): CyclotronJobInvocation => ({
            id: randomUUID(),
            teamId: team.id,
            functionId: fn.id,
            state: null,
            queue: 'hog',
            queuePriority: 0,
        })

        const enqueue = (topic: string, invocation: CyclotronJobInvocation): Promise<void> =>
            producer.produce({
                topic,
                partition: topic === HOG_TOPIC ? 0 : undefined,
                key: Buffer.from(invocation.id),
                value: Buffer.from(JSON.stringify(serializeInvocation(invocation))),
                headers: { functionId: invocation.functionId, teamId: String(invocation.teamId) },
            })

        const divert = (invocation: CyclotronJobInvocation): Promise<void> => enqueue(DIVERT_TOPIC, invocation)

        const quarantined = (
            errorKind: string = QUARANTINED_ERROR_KIND
        ): { invocation_id: string; function_id: string; team_id: number }[] =>
            results
                .getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)
                .map((x) => x.value as Record<string, unknown>)
                .filter((row) => row.error_kind === errorKind)
                .map(({ invocation_id, function_id, team_id }) => ({
                    invocation_id: invocation_id as string,
                    function_id: function_id as string,
                    team_id: team_id as number,
                }))

        const executions = (): number => mockFetch.mock.calls.length

        const attemptsAt = (groupId: string, partition: number, offset: number): Promise<string | null> =>
            quarantineFor('enforce').valkey.useClient({ name: 'test' }, (client) =>
                client.hget(batchAttemptsKey(groupId, partition, offset), 'attempts')
            )

        const watchedState = async (fn: HogFunctionType): Promise<HogWatcherState> =>
            (await watchers.hogWatcher.getPersistedState(fn.id)).state

        const forceState = async (fn: HogFunctionType, state: HogWatcherState): Promise<void> => {
            await watchers.hogWatcher.forceStateChange(fn, state)
            await watchers.hogWatcherMirror.forceStateChange(fn, state)
            mockCaptureTeamEvent.mockClear()
        }

        const stateChanges = () =>
            mockCaptureTeamEvent.mock.calls
                .filter(([, event]) => event === 'hog_function_state_change')
                .map(([, , properties]) => ({ id: properties.hog_function_id, state: properties.state }))

        const isUnavailable = expect.objectContaining({ code: Code.Unavailable, isRetriable: true })

        const reportedQuarantines = async (fn: HogFunctionType): Promise<number | undefined> =>
            (await register.getSingleMetric('cdp_quarantined_functions')!.get()).values.find(
                (v) => v.labels.function_id === fn.id && v.labels.team_id === String(team.id)
            )?.value

        it.each([
            ['v1', false],
            ['v2', true],
        ])(
            'quarantines the poisoned invocation of a diverted batch and runs the healthy one, with consumer %s',
            async (_, useV2) => {
                const configuredV2 = defaultConfig.CONSUMER_USE_V2
                defaultConfig.CONSUMER_USE_V2 = useV2
                try {
                    const poison = poisonedInvocation()
                    await divert(poison)
                    await divert(healthyInvocation())

                    expect(await dlqCrashLoop(MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(TypeError)))
                    expect(executions()).toEqual(0)

                    const quarantinedBefore = await counter('cdp_invocations_quarantined_total', {
                        outcome: 'recorded',
                    })
                    let worker = await startDlqWorker()
                    await waitForExpect(() => expect(executions()).toEqual(1), 30_000)
                    expect(quarantined()).toEqual([
                        { invocation_id: poison.id, function_id: poisonFn.id, team_id: team.id },
                    ])
                    expect(await counter('cdp_invocations_quarantined_total', { outcome: 'recorded' })).toEqual(
                        quarantinedBefore + 1
                    )

                    await divert(healthyInvocation())
                    await waitForExpect(() => expect(executions()).toEqual(2), 30_000)
                    await stopCdpWorker(worker)

                    // A restart replays nothing, because the worker committed past the quarantined message.
                    worker = await startDlqWorker()
                    await divert(healthyInvocation())
                    await waitForExpect(() => expect(executions()).toEqual(3), 30_000)
                    expect(quarantined()).toHaveLength(1)
                } finally {
                    defaultConfig.CONSUMER_USE_V2 = configuredV2
                }
            }
        )

        it('never quarantines an invocation that only failed while personhog was down', async () => {
            personsDown = true
            await divert(healthyInvocation({ withPerson: false }))

            const crashes = await dlqCrashLoop(MAX_ATTEMPTS + 1)
            expect(crashes).toEqual(Array(MAX_ATTEMPTS + 1).fill(isUnavailable))

            personsDown = false
            await startDlqWorker()
            await waitForExpect(() => expect(executions()).toEqual(1), 30_000)
            expect(quarantined()).toEqual([])
        })

        it('reports a function whose poisoned invocations crash both workers until they are quarantined, and skips the rest once a person disables it', async () => {
            const poisons = [poisonedInvocation(), poisonedInvocation(), poisonedInvocation()]
            for (const poison of poisons) {
                await enqueue(HOG_TOPIC, poison)
            }
            const divertedBefore = await counter('cdp_batch_diverted_messages_total', { group: HOG_GROUP })

            const hogCrashes = await cdpCrashLoop('hog', poisons.length * MAX_ATTEMPTS)
            expect(hogCrashes).toEqual(Array(poisons.length * MAX_ATTEMPTS).fill(expect.any(TypeError)))
            await startCdpWorker('hog')
            await waitForExpect(
                async () =>
                    expect(await counter('cdp_batch_diverted_messages_total', { group: HOG_GROUP })).toEqual(
                        divertedBefore + poisons.length
                    ),
                30_000
            )
            await enqueue(HOG_TOPIC, healthyInvocation())
            await waitForExpect(() => expect(executions()).toEqual(1), 30_000)
            const remaining = poisonedInvocation()

            const dlqCrashes = await dlqCrashLoop(poisons.length * MAX_ATTEMPTS)
            expect(dlqCrashes).toEqual(Array(poisons.length * MAX_ATTEMPTS).fill(expect.any(TypeError)))
            const dlqWorker = await startDlqWorker()
            await waitForExpect(() => expect(quarantined()).toHaveLength(poisons.length), 30_000)
            expect(quarantined().map((x) => x.invocation_id)).toEqual(poisons.map((x) => x.id))
            await waitForExpect(async () => expect(await reportedQuarantines(poisonFn)).toEqual(poisons.length), 30_000)
            expect(await watchedState(poisonFn)).toEqual(HogWatcherState.healthy)

            // The runbook of the gauge's alert has a person disable the function.
            await forceState(poisonFn, HogWatcherState.forcefully_disabled)
            await stopCdpWorker(dlqWorker)
            await divert(remaining)
            await startDlqWorker()
            await waitForExpect(
                () =>
                    expect(quarantined(SKIPPED_FUNCTION_DISABLED_ERROR_KIND)).toEqual([
                        { invocation_id: remaining.id, function_id: poisonFn.id, team_id: team.id },
                    ]),
                30_000
            )

            expect(stateChanges()).toEqual([])

            // The hog worker runs whatever reaches its topic. The events consumer is what stops queuing a
            // disabled function, so a new event reaches only the healthy function.
            const eventsQueue = new CyclotronJobQueueKafka(undefined, hub, hub.CONSUMER_BATCH_SIZE)
            await eventsQueue.startAsProducer()
            try {
                const eventsConsumer = new CdpEventsConsumer(hub, deps(), {
                    hogQueue: eventsQueue,
                    hogflowQueue: eventsQueue,
                })
                const { invocations } = await eventsConsumer.processBatch([
                    createHogExecutionGlobals({ project: { id: team.id, name: team.name, url: '' } }),
                ])
                expect(invocations.map((x) => x.functionId)).toEqual([healthyFn.id])
                await waitForExpect(() => expect(executions()).toEqual(2), 30_000)
            } finally {
                await eventsQueue.stopProducer()
            }
        })

        it('leaves a function with fewer quarantines than the threshold off the gauge and healthy', async () => {
            const poisons = [poisonedInvocation(), poisonedInvocation()]
            for (const poison of poisons) {
                await divert(poison)
            }

            await dlqCrashLoop(poisons.length * MAX_ATTEMPTS)
            await startDlqWorker()
            await waitForExpect(() => expect(quarantined()).toHaveLength(poisons.length), 30_000)

            expect(await reportedQuarantines(poisonFn)).toBeUndefined()
            expect(await watchedState(poisonFn)).toEqual(HogWatcherState.healthy)
            expect(stateChanges()).toEqual([])
        })

        it('diverts nothing while personhog is down and runs the batch once it is back', async () => {
            personsDown = true
            const healthy = healthyInvocation({ withPerson: false })
            await enqueue(HOG_TOPIC, healthy)

            expect(await cdpCrashLoop('hog', MAX_ATTEMPTS + 1)).toEqual(Array(MAX_ATTEMPTS + 1).fill(isUnavailable))
            expect(Number(await attemptsAt(HOG_GROUP, 0, hogStart))).toBeLessThanOrEqual(MAX_ATTEMPTS)

            personsDown = false
            await startCdpWorker('hog')
            await waitForExpect(() => expect(executions()).toEqual(1), 30_000)
            expect(await divertedWithKey(healthy.id)).toEqual([])
        })

        it('still diverts a poison behind a personhog outage, and only the poison', async () => {
            personsDown = true
            const healthy = healthyInvocation({ withPerson: false })
            const poison = poisonedInvocation()
            await enqueue(HOG_TOPIC, healthy)
            await enqueue(HOG_TOPIC, poison)

            expect(await cdpCrashLoop('hog', MAX_ATTEMPTS + 1)).toEqual(Array(MAX_ATTEMPTS + 1).fill(isUnavailable))

            personsDown = false
            expect(await cdpCrashLoop('hog', MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(TypeError)))
            const divertedBefore = await counter('cdp_batch_diverted_messages_total', { group: HOG_GROUP })
            await startCdpWorker('hog')
            await waitForExpect(
                async () =>
                    expect(await counter('cdp_batch_diverted_messages_total', { group: HOG_GROUP })).toEqual(
                        divertedBefore + 1
                    ),
                30_000
            )

            expect(await divertedWithKey(poison.id)).toHaveLength(1)
            expect(await divertedWithKey(healthy.id)).toEqual([])
            expect(executions()).toEqual(1)
        })
    })
})
