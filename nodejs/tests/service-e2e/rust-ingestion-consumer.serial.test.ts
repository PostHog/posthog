import net from 'net'
import {
    ConsumerGlobalConfig,
    KafkaConsumer,
    LibrdKafkaError,
    Message,
    Metadata,
    TopicPartitionOffset,
    WatermarkOffsets,
} from 'node-rdkafka'
import path from 'path'

import {
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
} from '~/common/config/kafka-topics'
import { KafkaProducerWrapper, MessageWithoutTopic } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, createKafkaTestTopicName, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { ServiceProcess, getFreePort } from '~/tests/helpers/service-process'

import { Clickhouse } from '../helpers/clickhouse'
import {
    DEFAULT_TEAM,
    EventBuilder,
    createKafkaMessage,
    fetchEvents,
    waitForClickHouseKafkaConsumer,
    waitForKafkaMessages,
} from '../helpers/ingestion-e2e'
import { resetTestDatabase } from '../helpers/sql'

jest.setTimeout(300_000)

const REPO_ROOT = path.resolve(__dirname, '../../..')
const NODEJS_ROOT = path.join(REPO_ROOT, 'nodejs')
const RUST_ROOT = path.join(REPO_ROOT, 'rust')

const TEST_TEAM_ID = 2
const TEST_TEAM_TOKEN = `THIS IS NOT A TOKEN FOR TEAM ${TEST_TEAM_ID}`
// Each worker serves its WorkerIngest stream on its HTTP port plus this offset;
// the Rust consumer derives the stream address the same way.
const GRPC_PORT_OFFSET = 1
const POSTGRES_URL = 'postgres://posthog:posthog@localhost:5432'
const NODE_WORKER_COUNT = 2
const RUST_BATCH_SIZE = 10
const E2E_EVENT_COUNT = RUST_BATCH_SIZE * 2

interface NodeWorker {
    service: ServiceProcess
    url: string
}

interface RustNodeStack {
    workers: NodeWorker[]
    rustConsumer: ServiceProcess
    rustMetricsPort: number
    groupId: string
}

type TestEvent = ReturnType<EventBuilder['build']>

interface KafkaOutputEvent {
    uuid: string
    distinct_id: string
    properties: string
    team_id: number
}

type TopicWatermarks = { partition: number; offsets: WatermarkOffsets }[]

// Per-test isolation state. Each test produces to a unique input topic and reads only the
// output-topic messages produced after the watermarks captured at the start of the test,
// so we never delete the shared topics that ClickHouse's Kafka consumers subscribe to.
let currentIngestionTopic = KAFKA_EVENTS_PLUGIN_INGESTION
let outputTopicStartWatermarks = new Map<string, TopicWatermarks>()

describe('Rust ingestion consumer with Node ingestion API workers', () => {
    let clickhouse: Clickhouse
    let services: ServiceProcess[] = []

    beforeAll(() => {
        configureParentTestEnv()
        clickhouse = Clickhouse.create()
    })

    beforeEach(async () => {
        currentIngestionTopic = createKafkaTestTopicName(KAFKA_EVENTS_PLUGIN_INGESTION)
        await ensureKafkaTopics([...TEST_KAFKA_TOPICS, currentIngestionTopic])
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        await waitForClickHouseKafkaConsumer(clickhouse)
        outputTopicStartWatermarks = await captureTopicStartWatermarks([
            KAFKA_EVENTS_JSON,
            KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
        ])
    })

    afterEach(async () => {
        await Promise.allSettled(services.map((service) => service.stop()))
        // stop() returns when the direct child (pnpm) exits; the node process it spawned
        // can still be draining its gRPC listener. Do not let the next test allocate
        // ports while they are held.
        await waitForPortsFree(workerPortsInUse.splice(0))
        services = []
        outputTopicStartWatermarks = new Map()
    })

    afterAll(async () => {
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickhouse.close()
    })

    test('Rust consumer ingests Kafka events through multiple real Node ingestion API workers', async () => {
        const workers = await startNodeWorkerSet(services)
        const producer = await KafkaProducerWrapper.create(undefined)
        const team = { ...DEFAULT_TEAM, id: TEST_TEAM_ID, api_token: TEST_TEAM_TOKEN }
        const initialEvents = buildBatchBoundaryEvents(team, 'rust node e2e event', 'initial')

        try {
            await produceEvents(producer, initialEvents)
            const { rustConsumer, rustMetricsPort, groupId } = await startRustConsumerForWorkers(services, workers)
            await waitForEvents(clickhouse, initialEvents)
            await assertKafkaIngestionState(groupId, initialEvents)

            const ingestedEvents = await fetchEvents(clickhouse, TEST_TEAM_ID)
            expect(ingestedEvents).toHaveLength(E2E_EVENT_COUNT)

            const metricsAfterInitialBatch = await waitForRoutedMetrics(rustConsumer, rustMetricsPort, {
                expectedMessages: initialEvents.length,
                expectedWorkers: [workers[0].url, workers[1].url],
                expectedMinCommits: 2,
            })
            const initialWorker0Routed = getPrometheusSample(metricsAfterInitialBatch, {
                name: 'ingestion_consumer_dispatcher_messages_routed_total',
                labels: { worker: workers[0].url },
            })
            const initialWorker1Routed = getPrometheusSample(metricsAfterInitialBatch, {
                name: 'ingestion_consumer_dispatcher_messages_routed_total',
                labels: { worker: workers[1].url },
            })
            expect(initialWorker0Routed).toBeGreaterThan(0)
            expect(initialWorker1Routed).toBeGreaterThan(0)
            expect(
                workers.reduce(
                    (sum, worker) =>
                        sum +
                        getPrometheusSample(metricsAfterInitialBatch, {
                            name: 'ingestion_consumer_transport_requests_total',
                            labels: { worker: worker.url, status: 'ok' },
                        }),
                    0
                )
            ).toBeGreaterThanOrEqual(NODE_WORKER_COUNT)
        } finally {
            await producer.disconnect()
        }
    })

    test('Rust consumer commits a mixed batch after Node DLQs an invalid event', async () => {
        const workers = await startNodeWorkerSet(services)
        const producer = await KafkaProducerWrapper.create(undefined)
        const team = { ...DEFAULT_TEAM, id: TEST_TEAM_ID, api_token: TEST_TEAM_TOKEN }
        const invalidUuid = 'not-a-valid-event-uuid'
        const events = buildBatchBoundaryEvents(team, 'rust node e2e mixed validity event', 'mixed').map(
            (event, index) => (index === 3 ? { ...event, uuid: invalidUuid } : event)
        )
        const validEvents = events.filter((event) => event.uuid !== invalidUuid)

        try {
            await produceEvents(producer, events)
            const { rustConsumer, rustMetricsPort, groupId } = await startRustConsumerForWorkers(services, workers)

            await waitForEvents(clickhouse, validEvents)
            expectKafkaOutputEvents(await readTopicMessages(KAFKA_EVENTS_JSON, validEvents.length), validEvents)
            const [dlqMessage] = await readTopicMessages(KAFKA_EVENTS_PLUGIN_INGESTION_DLQ, 1)
            expectDlqMessage(dlqMessage, {
                topic: currentIngestionTopic,
                event: 'rust node e2e mixed validity event',
                uuid: invalidUuid,
            })
            await expectCommittedOffsetsAtTopicEnd(groupId, currentIngestionTopic, events.length)
            await waitForOffsetCommitCount(rustConsumer, rustMetricsPort, 2)
        } finally {
            await producer.disconnect()
        }
    })

    test('Rust consumer handles healthy, failed, and recovered Node ingestion API workers across batches', async () => {
        const { workers, rustConsumer, rustMetricsPort, groupId } = await startRustNodeStack(services)
        const producer = await KafkaProducerWrapper.create(undefined)
        const team = { ...DEFAULT_TEAM, id: TEST_TEAM_ID, api_token: TEST_TEAM_TOKEN }
        const distinctIds = createDistinctIds(8)
        const allEvents: TestEvent[] = []

        try {
            const healthyEvents = buildSingleBatchEvents(
                team,
                'rust node e2e healthy worker event',
                'healthy',
                0,
                distinctIds
            )
            allEvents.push(...healthyEvents)
            await produceEvents(producer, healthyEvents)
            await waitForEvents(clickhouse, allEvents)
            await assertKafkaIngestionState(groupId, allEvents)
            await waitForRoutedMetrics(rustConsumer, rustMetricsPort, {
                expectedMessages: healthyEvents.length,
                expectedWorkers: [workers[0].url, workers[1].url],
                expectedMinCommits: 1,
            })

            const metricsAfterHealthyBatch = await fetchMetrics(rustConsumer, rustMetricsPort)
            const worker0RoutedAfterHealthyBatch = getPrometheusSample(metricsAfterHealthyBatch, {
                name: 'ingestion_consumer_dispatcher_messages_routed_total',
                labels: { worker: workers[0].url },
            })
            const worker1RoutedAfterHealthyBatch = getPrometheusSample(metricsAfterHealthyBatch, {
                name: 'ingestion_consumer_dispatcher_messages_routed_total',
                labels: { worker: workers[1].url },
            })
            expect(worker0RoutedAfterHealthyBatch).toBeGreaterThan(0)
            expect(worker1RoutedAfterHealthyBatch).toBeGreaterThan(0)

            await workers[0].service.stop()
            await waitForWorkerHealthState(rustConsumer, rustMetricsPort, workers[0].url, 'unhealthy')
            const failoverEvents = buildSingleBatchEvents(
                team,
                'rust node e2e failover event',
                'failover',
                1,
                distinctIds
            )
            allEvents.push(...failoverEvents)
            await produceEvents(producer, failoverEvents)
            await waitForEvents(clickhouse, allEvents)
            await assertKafkaIngestionState(groupId, allEvents)
            await waitForOffsetCommitCount(rustConsumer, rustMetricsPort, 2)

            await waitForExpect(async () => {
                const metrics = await fetchMetrics(rustConsumer, rustMetricsPort)
                expect(
                    getPrometheusSample(metrics, {
                        name: 'ingestion_consumer_dispatcher_messages_routed_total',
                        labels: { worker: workers[0].url },
                    })
                ).toBe(worker0RoutedAfterHealthyBatch)
                expect(
                    getPrometheusSample(metrics, {
                        name: 'ingestion_consumer_dispatcher_messages_routed_total',
                        labels: { worker: workers[1].url },
                    })
                ).toBeGreaterThanOrEqual(worker1RoutedAfterHealthyBatch + failoverEvents.length)
                expect(
                    getPrometheusSample(metrics, {
                        name: 'ingestion_consumer_worker_state_transitions_total',
                        labels: { worker: workers[0].url, from: 'healthy', to: 'unhealthy' },
                    })
                ).toBeGreaterThanOrEqual(1)
            }, 30_000)

            const metricsBeforeRecovery = await fetchMetrics(rustConsumer, rustMetricsPort)
            const worker0RoutedBeforeRecovery = getPrometheusSample(metricsBeforeRecovery, {
                name: 'ingestion_consumer_dispatcher_messages_routed_total',
                labels: { worker: workers[0].url },
            })

            workers[0] = await restartNodeIngestionApiWorker(services, workers[0], 'node-worker-1-recovered')
            await waitForWorkerHealthState(rustConsumer, rustMetricsPort, workers[0].url, 'healthy')

            const recoveryEvents = buildSingleBatchEvents(
                team,
                'rust node e2e recovery event',
                'recovery',
                2,
                distinctIds
            )
            allEvents.push(...recoveryEvents)
            await produceEvents(producer, recoveryEvents)
            await waitForEvents(clickhouse, allEvents)
            await assertKafkaIngestionState(groupId, allEvents)
            await waitForOffsetCommitCount(rustConsumer, rustMetricsPort, 3)

            await waitForExpect(async () => {
                const metrics = await fetchMetrics(rustConsumer, rustMetricsPort)
                expect(
                    getPrometheusSample(metrics, {
                        name: 'ingestion_consumer_dispatcher_messages_routed_total',
                        labels: { worker: workers[0].url },
                    })
                ).toBeGreaterThan(worker0RoutedBeforeRecovery)
                expect(
                    getPrometheusSample(metrics, {
                        name: 'ingestion_consumer_worker_state_transitions_total',
                        labels: { worker: workers[0].url, from: 'unhealthy', to: 'degraded' },
                    })
                ).toBeGreaterThanOrEqual(1)
                expect(
                    getPrometheusSample(metrics, {
                        name: 'ingestion_consumer_worker_state_transitions_total',
                        labels: { worker: workers[0].url, from: 'degraded', to: 'healthy' },
                    })
                ).toBeGreaterThanOrEqual(1)
            }, 30_000)
        } finally {
            await producer.disconnect()
        }
    })

    test('Rust consumer holds the batch then exits when all Node ingestion API workers stay down', async () => {
        // During a full worker outage the consumer must hold the batch (nothing
        // dropped, nothing committed) and retry for the configured deferred-flush
        // timeout, then exit non-zero so the pod restarts and Kafka redelivers.
        // A short timeout keeps the bounded-exit contract observable quickly.
        const { workers, rustConsumer, rustMetricsPort } = await startRustNodeStack(services, {
            CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS: '5000',
        })
        const producer = await KafkaProducerWrapper.create(undefined)
        const team = { ...DEFAULT_TEAM, id: TEST_TEAM_ID, api_token: TEST_TEAM_TOKEN }
        const distinctIds = createDistinctIds(8)

        try {
            await Promise.all(workers.map((worker) => worker.service.stop()))
            await Promise.all(
                workers.map((worker) =>
                    waitForWorkerHealthState(rustConsumer, rustMetricsPort, worker.url, 'unhealthy')
                )
            )

            const events = buildSingleBatchEvents(
                team,
                'rust node e2e total worker failure event',
                'failure',
                0,
                distinctIds
            )
            await produceEvents(producer, events)

            const exit = await rustConsumer.waitForExit(60_000)
            expect(exit.exitCode).not.toBe(0)
            expect(exit.output).toContain('deferred messages made no progress within the flush timeout')
            await waitForTopicMessageCount(KAFKA_EVENTS_JSON, 0)
        } finally {
            await producer.disconnect()
        }
    })
})

function configureParentTestEnv(): void {
    process.env.KAFKA_HOSTS = 'localhost:9092'
    process.env.KAFKA_PRODUCER_METADATA_BROKER_LIST = 'localhost:9092'
    process.env.DATABASE_URL = `${POSTGRES_URL}/test_posthog`
    process.env.PERSONS_DATABASE_URL = `${POSTGRES_URL}/test_persons`
    process.env.PERSONS_READONLY_DATABASE_URL = `${POSTGRES_URL}/test_persons`
    process.env.BEHAVIORAL_COHORTS_DATABASE_URL = `${POSTGRES_URL}/test_behavioral_cohorts`
    process.env.CLICKHOUSE_HOST = 'localhost'
    process.env.CLICKHOUSE_DATABASE = 'posthog_test'
    process.env.REDIS_URL = 'redis://127.0.0.1'
}

async function startNodeIngestionApiWorkers(count: number): Promise<NodeWorker[]> {
    const workers: NodeWorker[] = []
    for (let i = 0; i < count; i++) {
        workers.push(await startNodeIngestionApiWorker(`node-worker-${i + 1}`))
    }
    return workers
}

async function startNodeWorkerSet(services: ServiceProcess[]): Promise<NodeWorker[]> {
    const workers = await startNodeIngestionApiWorkers(NODE_WORKER_COUNT)
    services.push(...workers.map((worker) => worker.service))
    return workers
}

async function startRustConsumerForWorkers(
    services: ServiceProcess[],
    workers: NodeWorker[],
    extraRustEnv: Record<string, string> = {}
): Promise<Omit<RustNodeStack, 'workers'>> {
    const rustMetricsPort = await getFreePort()
    const groupId = `rust-node-e2e-${Date.now()}-${Math.random().toString(16).slice(2)}`
    const rustConsumer = startRustIngestionConsumer(
        'rust-consumer',
        workers.map((worker) => worker.url),
        rustMetricsPort,
        groupId,
        extraRustEnv
    )
    services.push(rustConsumer)
    await rustConsumer.waitForHttpOk(`http://127.0.0.1:${rustMetricsPort}/_readiness`)

    return { rustConsumer, rustMetricsPort, groupId }
}

async function startRustNodeStack(
    services: ServiceProcess[],
    extraRustEnv: Record<string, string> = {}
): Promise<RustNodeStack> {
    const workers = await startNodeWorkerSet(services)
    const rust = await startRustConsumerForWorkers(services, workers, extraRustEnv)
    return { workers, ...rust }
}

// Every port a worker has listened on this test, so afterEach can wait for them to be
// released before the next test allocates.
const workerPortsInUse: number[] = []

async function startNodeIngestionApiWorker(name: string, port?: number): Promise<NodeWorker> {
    // A free-port check is a snapshot: another socket can take the port before the
    // worker binds it. Unpinned starts retry with a fresh pair; pinned restarts wait
    // for the previous holder to let go (see restartNodeIngestionApiWorker).
    for (let attempt = 1; ; attempt++) {
        const workerPort = port ?? (await getFreeWorkerPort())
        try {
            return await spawnNodeIngestionApiWorker(name, workerPort)
        } catch (error) {
            const addressInUse = error instanceof Error && error.message.includes('EADDRINUSE')
            if (port !== undefined || !addressInUse || attempt >= 3) {
                throw error
            }
        }
    }
}

async function spawnNodeIngestionApiWorker(name: string, workerPort: number): Promise<NodeWorker> {
    const service = new ServiceProcess(name, 'pnpm', ['exec', 'tsx', 'src/index.ts'], {
        cwd: NODEJS_ROOT,
        env: {
            ...serviceProcessEnv(),
            ...testDependencyEnv(),
            ...testTopicEnv(),
            NODE_ENV: 'dev',
            PLUGIN_SERVER_MODE: 'ingestion-api',
            HTTP_SERVER_PORT: workerPort.toString(),
            INGESTION_API_GRPC_PORT: (workerPort + GRPC_PORT_OFFSET).toString(),
            OTEL_SDK_DISABLED: 'true',
            DISABLE_OPENTELEMETRY_TRACING: 'true',
            LOG_LEVEL: 'warn',
            INGESTION_WORKER_CONCURRENT_BATCHES: '1',
            PROPERTY_DEFS_WRITE_DISABLED: 'true',
            PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS: '',
        },
    })

    const url = `http://127.0.0.1:${workerPort}`
    await service.waitForHttpOk(`${url}/_ready`)
    // Only a worker that actually bound its ports owns them; a failed attempt's pair
    // belongs to whatever foreign socket caused the collision.
    workerPortsInUse.push(workerPort, workerPort + GRPC_PORT_OFFSET)
    return { service, url }
}

// A worker needs two adjacent free ports: HTTP, and HTTP + GRPC_PORT_OFFSET for the stream.
async function getFreeWorkerPort(): Promise<number> {
    for (let attempt = 0; attempt < 20; attempt++) {
        const port = await getFreePort()
        if (await isPortFree(port + GRPC_PORT_OFFSET)) {
            return port
        }
    }
    throw new Error('could not find adjacent free ports for a worker')
}

function isPortFree(port: number): Promise<boolean> {
    return new Promise((resolve) => {
        const server = net.createServer()
        server.once('error', () => resolve(false))
        server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)))
    })
}

// Poll until every port can be bound. A stopped worker's node process releases its
// listeners only after its graceful shutdown (gRPC drain), which outlives the pnpm
// wrapper that ServiceProcess.stop() waits on.
async function waitForPortsFree(ports: number[], timeoutMs = 15_000): Promise<void> {
    const deadline = Date.now() + timeoutMs
    for (const port of ports) {
        while (!(await isPortFree(port))) {
            if (Date.now() > deadline) {
                throw new Error(`port ${port} was not released within ${timeoutMs}ms`)
            }
            await new Promise((resolve) => setTimeout(resolve, 100))
        }
    }
}

async function restartNodeIngestionApiWorker(
    services: ServiceProcess[],
    worker: NodeWorker,
    name: string
): Promise<NodeWorker> {
    const port = Number(new URL(worker.url).port)
    await waitForPortsFree([port, port + GRPC_PORT_OFFSET])
    const restartedWorker = await startNodeIngestionApiWorker(name, port)
    services.push(restartedWorker.service)
    return restartedWorker
}

function startRustIngestionConsumer(
    name: string,
    workers: string[],
    metricsPort: number,
    groupId: string,
    extraEnv: Record<string, string> = {}
): ServiceProcess {
    return new ServiceProcess(name, 'cargo', ['run', '-p', 'ingestion-consumer'], {
        cwd: RUST_ROOT,
        env: {
            ...serviceProcessEnv(),
            RUST_LOG: 'info',
            KAFKA_HOSTS: 'localhost:9092',
            INGESTION_CONSUMER_CONSUME_TOPIC: currentIngestionTopic,
            INGESTION_CONSUMER_GROUP_ID: groupId,
            // Rust's generic KAFKA_CONSUMER_* parser maps this name to invalid rdkafka key "offset.reset".
            KAFKA_CONSUMER_OFFSET_RESET: undefined,
            KAFKA_CONSUMER_AUTO_OFFSET_RESET: 'earliest',
            CONSUMER_BATCH_SIZE: RUST_BATCH_SIZE.toString(),
            CONSUMER_BATCH_TIMEOUT_MS: '1000',
            CONSUMER_MAX_BACKGROUND_TASKS: '1',
            INGESTION_WORKER_CONCURRENT_BATCHES: '1',
            WORKER_ADDRESSES: workers.join(','),
            INGESTION_WORKER_GRPC_PORT_OFFSET: GRPC_PORT_OFFSET.toString(),
            WORKER_PROBE_INTERVAL_MS: '250',
            WORKER_DEAD_DECLARATION_MS: '750',
            WORKER_MIN_STATE_DURATION_MS: '100',
            WORKER_PROBE_FAILURE_THRESHOLD: '1',
            WORKER_DEGRADED_HOLD_MS: '250',
            BIND_HOST: '127.0.0.1',
            BIND_PORT: metricsPort.toString(),
            EXPORT_PROMETHEUS: 'true',
            ...extraEnv,
        },
    })
}

function serviceProcessEnv(): NodeJS.ProcessEnv {
    const env = { ...process.env }
    delete env.NODE_OPTIONS
    delete env.VSCODE_INSPECTOR_OPTIONS
    return env
}

function testDependencyEnv(): NodeJS.ProcessEnv {
    return {
        DATABASE_URL: `${POSTGRES_URL}/test_posthog`,
        PERSONS_DATABASE_URL: `${POSTGRES_URL}/test_persons`,
        PERSONS_READONLY_DATABASE_URL: `${POSTGRES_URL}/test_persons`,
        BEHAVIORAL_COHORTS_DATABASE_URL: `${POSTGRES_URL}/test_behavioral_cohorts`,
        CYCLOTRON_NODE_DATABASE_URL: `${POSTGRES_URL}/test_cyclotron_node`,
        KAFKA_HOSTS: 'localhost:9092',
        KAFKA_PRODUCER_METADATA_BROKER_LIST: 'localhost:9092',
        KAFKA_WARPSTREAM_PRODUCER_METADATA_BROKER_LIST: 'localhost:9092',
        KAFKA_INGESTION_PRODUCER_METADATA_BROKER_LIST: 'localhost:9092',
        CLICKHOUSE_HOST: 'localhost',
        CLICKHOUSE_DATABASE: 'posthog_test',
        CLICKHOUSE_SECURE: 'false',
        CLICKHOUSE_VERIFY: 'false',
        REDIS_URL: 'redis://127.0.0.1',
        SITE_URL: 'https://example.com',
    }
}

function testTopicEnv(): NodeJS.ProcessEnv {
    return {
        INGESTION_CONSUMER_CONSUME_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
        INGESTION_CONSUMER_DLQ_TOPIC: 'events_plugin_ingestion_dlq_test',
        INGESTION_CONSUMER_OVERFLOW_TOPIC: 'events_plugin_ingestion_overflow_test',
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: KAFKA_EVENTS_JSON,
        CLICKHOUSE_AI_EVENTS_KAFKA_TOPIC: 'clickhouse_ai_events_json_test',
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: 'clickhouse_heatmap_events_test',
        INGESTION_OUTPUT_EVENTS_TOPIC: KAFKA_EVENTS_JSON,
        INGESTION_OUTPUT_AI_EVENTS_TOPIC: 'clickhouse_ai_events_json_test',
        INGESTION_OUTPUT_HEATMAPS_TOPIC: 'clickhouse_heatmap_events_test',
        INGESTION_OUTPUT_INGESTION_WARNINGS_TOPIC: 'clickhouse_ingestion_warnings_test',
        INGESTION_OUTPUT_DLQ_TOPIC: 'events_plugin_ingestion_dlq_test',
        INGESTION_OUTPUT_OVERFLOW_TOPIC: 'events_plugin_ingestion_overflow_test',
        INGESTION_OUTPUT_ASYNC_TOPIC: 'events_plugin_ingestion_async_test',
        INGESTION_OUTPUT_GROUPS_TOPIC: 'clickhouse_groups_test',
        INGESTION_OUTPUT_PERSONS_TOPIC: 'clickhouse_person_test',
        INGESTION_OUTPUT_PERSON_DISTINCT_IDS_TOPIC: 'clickhouse_person_distinct_id_test',
        INGESTION_OUTPUT_APP_METRICS_TOPIC: 'clickhouse_app_metrics2_test',
        INGESTION_OUTPUT_LOG_ENTRIES_TOPIC: 'log_entries_test',
        INGESTION_OUTPUT_TOPHOG_TOPIC: 'clickhouse_tophog_test',
    }
}

function createDistinctIds(count: number): string[] {
    return Array.from({ length: count }, () => new UUIDT().toString())
}

function buildSingleBatchEvents(
    team: typeof DEFAULT_TEAM,
    eventName: string,
    phase: string,
    batchIndex: number,
    distinctIds: string[]
): TestEvent[] {
    const now = Date.now()
    const repeatedWithinBatch = [
        0,
        1,
        0,
        2,
        1,
        3,
        4,
        5,
        6,
        7, // ids 0 and 1 repeat within this 10-message batch
    ]

    return repeatedWithinBatch.map((distinctIdIndex, index) => {
        const eventIndex = batchIndex * RUST_BATCH_SIZE + index
        return new EventBuilder(team, distinctIds[distinctIdIndex])
            .withEvent(eventName)
            .withTimestamp(now + index)
            .withProperties({
                batchIndex,
                eventIndex,
                phase,
                sequence: eventIndex + 1,
            })
            .build()
    })
}

// Builds two 10-message batches where distinct IDs 0 and 1 repeat within each
// batch and across the batch boundary, so Kafka output ordering checks cover
// both intra-batch and inter-batch ordering for the same routing keys.
function buildBatchBoundaryEvents(team: typeof DEFAULT_TEAM, eventName: string, phase: string): TestEvent[] {
    const distinctIds = createDistinctIds(8)
    return [
        ...buildSingleBatchEvents(team, eventName, phase, 0, distinctIds),
        ...buildSingleBatchEvents(team, eventName, phase, 1, distinctIds),
    ]
}

async function produceEvents(producer: KafkaProducerWrapper, events: TestEvent[]): Promise<void> {
    for (const event of events) {
        const message = toProducerMessage(createKafkaMessageWithCaptureHeaders(event, TEST_TEAM_TOKEN))
        await producer.produce({
            topic: currentIngestionTopic,
            key: message.key ?? null,
            value: typeof message.value === 'string' ? Buffer.from(message.value) : message.value,
            headers: message.headers,
        })
    }

    await waitForKafkaMessages(producer)
}

function createKafkaMessageWithCaptureHeaders(event: TestEvent, token: string): Message {
    const message = createKafkaMessage(event, token)
    message.headers = [
        ...(message.headers ?? []),
        { event: Buffer.from(event.event ?? '') },
        { uuid: Buffer.from(event.uuid ?? '') },
    ]
    return message
}

async function waitForEvents(clickhouse: Clickhouse, events: TestEvent[]): Promise<void> {
    await waitForExpect(async () => {
        const ingestedEvents = await fetchEvents(clickhouse, TEST_TEAM_ID)
        expect(ingestedEvents.map((event) => event.uuid).sort()).toEqual(events.map((event) => event.uuid).sort())
    }, 60_000)
}

async function assertKafkaIngestionState(groupId: string, expectedEvents: TestEvent[]): Promise<void> {
    const outputMessages = await readTopicMessages(KAFKA_EVENTS_JSON, expectedEvents.length)
    expectKafkaOutputEvents(outputMessages, expectedEvents)
    await expectCommittedOffsetsAtTopicEnd(groupId, currentIngestionTopic, expectedEvents.length)
}

async function waitForTopicMessageCount(topic: string, expectedCount: number): Promise<void> {
    await withKafkaConsumer(
        `rust-node-e2e-count-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        async (consumer) => {
            await waitForExpect(async () => {
                expect(countSinceBaseline(topic, await getTopicWatermarks(consumer, topic))).toBe(expectedCount)
            }, 30_000)
        }
    )
}

async function readTopicMessages(topic: string, expectedCount: number): Promise<Message[]> {
    return await withKafkaConsumer(
        `rust-node-e2e-reader-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        async (consumer) => {
            const watermarks = await waitForTopicMessageCountAndGetWatermarks(consumer, topic, expectedCount)
            consumer.assign(
                watermarks.map(({ partition, offsets }) => ({
                    topic,
                    partition,
                    offset: baselineStartOffset(topic, partition, offsets.lowOffset),
                }))
            )

            const messages: Message[] = []
            const deadline = Date.now() + 30_000
            while (messages.length < expectedCount && Date.now() < deadline) {
                messages.push(...(await consumeKafkaMessages(consumer, expectedCount - messages.length)))
            }

            expect(messages).toHaveLength(expectedCount)
            return messages.sort((a, b) => a.partition - b.partition || a.offset - b.offset)
        }
    )
}

async function expectCommittedOffsetsAtTopicEnd(
    groupId: string,
    topic: string,
    expectedMessageCount: number
): Promise<void> {
    await withKafkaConsumer(groupId, async (consumer) => {
        await waitForExpect(async () => {
            const watermarks = await getTopicWatermarks(consumer, topic)
            const committed = await getCommittedOffsets(
                consumer,
                watermarks.map(({ partition }) => ({ topic, partition }))
            )

            expect(sumWatermarkMessageCount(watermarks)).toBe(expectedMessageCount)
            expect(sumCommittedOffsets(committed, watermarks)).toBe(expectedMessageCount)
            for (const { partition, offsets } of watermarks) {
                const committedOffset = committed.find((offset) => offset.partition === partition)?.offset
                expect(committedOffset).toBe(offsets.highOffset)
            }
        }, 30_000)
    })
}

async function waitForTopicMessageCountAndGetWatermarks(
    consumer: KafkaConsumer,
    topic: string,
    expectedCount: number
): Promise<TopicWatermarks> {
    let watermarks: TopicWatermarks = []
    await waitForExpect(async () => {
        watermarks = await getTopicWatermarks(consumer, topic)
        expect(countSinceBaseline(topic, watermarks)).toBe(expectedCount)
    }, 30_000)

    return watermarks
}

// Snapshots each topic's per-partition high offsets so later reads can isolate the
// messages produced during a single test, even though the topic is shared across tests.
async function captureTopicStartWatermarks(topics: string[]): Promise<Map<string, TopicWatermarks>> {
    return await withKafkaConsumer(
        `rust-node-e2e-watermarks-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        async (consumer) => {
            const entries = await Promise.all(
                topics.map(async (topic) => [topic, await getTopicWatermarks(consumer, topic)] as const)
            )
            return new Map(entries)
        }
    )
}

// The offset a test's reads should start from for a topic/partition: the high offset
// captured at the start of the test, or the current low offset for topics without a baseline.
function baselineStartOffset(topic: string, partition: number, fallbackLowOffset: number): number {
    const baseline = outputTopicStartWatermarks.get(topic)?.find((entry) => entry.partition === partition)
    return baseline?.offsets.highOffset ?? fallbackLowOffset
}

// Counts only the messages produced after the captured start watermarks for a topic.
function countSinceBaseline(topic: string, watermarks: TopicWatermarks): number {
    return watermarks.reduce(
        (sum, { partition, offsets }) =>
            sum + offsets.highOffset - baselineStartOffset(topic, partition, offsets.lowOffset),
        0
    )
}

async function getTopicWatermarks(
    consumer: KafkaConsumer,
    topic: string
): Promise<{ partition: number; offsets: WatermarkOffsets }[]> {
    const partitions = await getTopicPartitions(consumer, topic)
    return await Promise.all(
        partitions.map(async (partition) => ({
            partition,
            offsets: await queryWatermarkOffsets(consumer, topic, partition),
        }))
    )
}

async function getTopicPartitions(consumer: KafkaConsumer, topic: string): Promise<number[]> {
    const metadata = await getKafkaMetadata(consumer, topic)
    const topicMetadata = metadata.topics.find((metadataTopic) => metadataTopic.name === topic)
    if (!topicMetadata) {
        throw new Error(`Kafka topic ${topic} was not found in metadata`)
    }
    return topicMetadata.partitions.map((partition) => partition.id)
}

async function withKafkaConsumer<T>(groupId: string, fn: (consumer: KafkaConsumer) => Promise<T>): Promise<T> {
    const config = {
        'client.id': 'rust-node-e2e-inspector',
        'group.id': groupId,
        'metadata.broker.list': process.env.KAFKA_HOSTS ?? 'localhost:9092',
        'enable.auto.commit': false,
        'enable.partition.eof': true,
        'auto.offset.reset': 'earliest',
        log_level: 4,
    } as ConsumerGlobalConfig
    const consumer = new KafkaConsumer(config, {})

    await connectKafkaConsumer(consumer)
    try {
        return await fn(consumer)
    } finally {
        await disconnectKafkaConsumer(consumer)
    }
}

async function connectKafkaConsumer(consumer: KafkaConsumer): Promise<void> {
    await new Promise<void>((resolve, reject) => {
        consumer.once('ready', () => resolve())
        consumer.once('event.error', (error) => reject(error))
        consumer.connect()
    })
}

async function disconnectKafkaConsumer(consumer: KafkaConsumer): Promise<void> {
    if (!consumer.isConnected()) {
        return
    }

    await new Promise<void>((resolve, reject) => {
        consumer.disconnect((error) => {
            if (error) {
                reject(error)
            } else {
                resolve()
            }
        })
    })
}

async function getKafkaMetadata(consumer: KafkaConsumer, topic: string): Promise<Metadata> {
    return await new Promise((resolve, reject) => {
        consumer.getMetadata({ topic, timeout: 10_000 }, (error: LibrdKafkaError, metadata: Metadata) => {
            if (error) {
                reject(error)
            } else {
                resolve(metadata)
            }
        })
    })
}

async function queryWatermarkOffsets(
    consumer: KafkaConsumer,
    topic: string,
    partition: number
): Promise<WatermarkOffsets> {
    return await new Promise((resolve, reject) => {
        consumer.queryWatermarkOffsets(
            topic,
            partition,
            10_000,
            (error: LibrdKafkaError, offsets: WatermarkOffsets) => {
                if (error) {
                    reject(error)
                } else {
                    resolve(offsets)
                }
            }
        )
    })
}

async function getCommittedOffsets(
    consumer: KafkaConsumer,
    topicPartitions: { topic: string; partition: number }[]
): Promise<TopicPartitionOffset[]> {
    return await new Promise((resolve, reject) => {
        consumer.committed(topicPartitions, 10_000, (error, committedOffsets) => {
            if (error) {
                reject(error)
            } else {
                resolve(committedOffsets)
            }
        })
    })
}

async function consumeKafkaMessages(consumer: KafkaConsumer, count: number): Promise<Message[]> {
    return await new Promise((resolve, reject) => {
        consumer.consume(Math.max(count, 1), (error, messages) => {
            if (error) {
                reject(error)
            } else {
                resolve(messages)
            }
        })
    })
}

function sumWatermarkMessageCount(watermarks: { offsets: WatermarkOffsets }[]): number {
    return watermarks.reduce((sum, { offsets }) => sum + offsets.highOffset - offsets.lowOffset, 0)
}

function sumCommittedOffsets(
    committed: TopicPartitionOffset[],
    watermarks: { partition: number; offsets: WatermarkOffsets }[]
): number {
    return watermarks.reduce((sum, { partition, offsets }) => {
        const committedOffset = committed.find((offset) => offset.partition === partition)?.offset ?? offsets.lowOffset
        return sum + committedOffset - offsets.lowOffset
    }, 0)
}

function expectKafkaOutputEvents(messages: Message[], expectedEvents: TestEvent[]): void {
    const outputEvents = messages.map(parseKafkaOutputEvent)
    expect(outputEvents.map((event) => event.uuid).sort()).toEqual(expectedEvents.map((event) => event.uuid).sort())

    for (const distinctId of new Set(expectedEvents.map((event) => event.distinct_id))) {
        const expectedUuids = expectedEvents
            .filter((event) => event.distinct_id === distinctId)
            .map((event) => event.uuid)
        const actualUuids = outputEvents.filter((event) => event.distinct_id === distinctId).map((event) => event.uuid)
        expect(actualUuids).toEqual(expectedUuids)
    }
}

function expectDlqMessage(message: Message, expected: { topic: string; event: string; uuid: string }): void {
    if (!message.value) {
        throw new Error(`Kafka DLQ message at ${message.topic}:${message.partition}:${message.offset} had no value`)
    }

    const dlqPayload = parseJSON(message.value.toString()) as { uuid?: string; data?: string }
    const dlqEvent = dlqPayload.data ? (parseJSON(dlqPayload.data) as { event?: string }) : {}
    const dlqHeaders = kafkaHeadersToRecord(message.headers)
    expect(dlqPayload.uuid).toBe(expected.uuid)
    expect(dlqEvent.event).toBe(expected.event)
    expect(dlqHeaders.uuid).toBe(expected.uuid)
    expect(dlqHeaders.event).toBe(expected.event)
    expect(dlqHeaders.dlq_topic).toBe(expected.topic)
    expect(dlqHeaders.dlq_reason).toBeTruthy()
}

function parseKafkaOutputEvent(message: Message): KafkaOutputEvent {
    if (!message.value) {
        throw new Error(`Kafka output message at ${message.topic}:${message.partition}:${message.offset} had no value`)
    }

    return parseJSON(message.value.toString()) as KafkaOutputEvent
}

async function waitForRoutedMetrics(
    rustConsumer: ServiceProcess,
    rustMetricsPort: number,
    {
        expectedMessages,
        expectedMinCommits = 1,
        expectedWorkers,
    }: {
        expectedMessages: number
        expectedMinCommits?: number
        expectedWorkers: string[]
    }
): Promise<string> {
    let lastMetrics = ''

    await waitForExpect(async () => {
        lastMetrics = await fetchMetrics(rustConsumer, rustMetricsPort)
        const totalRouted = expectedWorkers.reduce(
            (sum, worker) =>
                sum +
                getPrometheusSample(lastMetrics, {
                    name: 'ingestion_consumer_dispatcher_messages_routed_total',
                    labels: { worker },
                }),
            0
        )

        expect(totalRouted).toBeGreaterThanOrEqual(expectedMessages)
        for (const worker of expectedWorkers) {
            expect(lastMetrics).toContain(
                `ingestion_consumer_dispatcher_sub_batches_assigned_total{worker="${worker}"}`
            )
        }
        expect(getOffsetCommitCount(lastMetrics)).toBeGreaterThanOrEqual(expectedMinCommits)
    }, 30_000)

    return lastMetrics
}

async function waitForOffsetCommitCount(
    rustConsumer: ServiceProcess,
    rustMetricsPort: number,
    expectedMinCommits: number
): Promise<void> {
    await waitForExpect(async () => {
        expect(getOffsetCommitCount(await fetchMetrics(rustConsumer, rustMetricsPort))).toBeGreaterThanOrEqual(
            expectedMinCommits
        )
    }, 30_000)
}

async function fetchMetrics(rustConsumer: ServiceProcess, rustMetricsPort: number): Promise<string> {
    const metrics = await rustConsumer.request(`http://127.0.0.1:${rustMetricsPort}/metrics`, { method: 'GET' })
    expect(metrics.statusCode).toBe(200)
    return metrics.body
}

async function waitForWorkerHealthState(
    rustConsumer: ServiceProcess,
    rustMetricsPort: number,
    worker: string,
    state: 'healthy' | 'degraded' | 'unhealthy'
): Promise<void> {
    await waitForExpect(async () => {
        const metrics = await fetchMetrics(rustConsumer, rustMetricsPort)
        expect(
            getPrometheusSample(metrics, {
                name: 'ingestion_consumer_worker_health_state',
                labels: { worker, state },
            })
        ).toBe(1)
    }, 30_000)
}

function getOffsetCommitCount(metrics: string): number {
    return getPrometheusSample(metrics, {
        name: 'ingestion_consumer_offset_commits_total',
    })
}

function getPrometheusSample(metrics: string, metric: { name: string; labels?: Record<string, string> }): number {
    for (const line of metrics.split('\n')) {
        if (!line || line.startsWith('#')) {
            continue
        }

        const parsedLine = /^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+eE0-9.]+)/.exec(line)
        if (!parsedLine || parsedLine[1] !== metric.name) {
            continue
        }

        const labels = parsePrometheusLabels(parsedLine[2] ?? '')
        const hasMatchingLabels = Object.entries(metric.labels ?? {}).every(([key, value]) => labels[key] === value)
        if (hasMatchingLabels) {
            return Number(parsedLine[3])
        }
    }

    return 0
}

function parsePrometheusLabels(labels: string): Record<string, string> {
    return Object.fromEntries(
        Array.from(labels.matchAll(/([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"/g)).map(([, key, value]) => [
            key,
            value.replace(/\\"/g, '"').replace(/\\\\/g, '\\'),
        ])
    )
}

function toProducerMessage(message: ReturnType<typeof createKafkaMessage>): MessageWithoutTopic {
    return {
        key: message.key?.toString(),
        value: message.value ?? null,
        headers: kafkaHeadersToRecord(message.headers),
    }
}

function kafkaHeadersToRecord(headers: Message['headers']): Record<string, string> {
    return Object.fromEntries(
        (headers ?? []).flatMap((header) =>
            Object.entries(header).map(([key, value]) => [key, value?.toString() ?? ''])
        )
    )
}
