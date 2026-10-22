// Serial e2e: the Kafka feeds behind the two person backends, compared from
// the real ingestion path. The Rust ingestion consumer feeds a Node ingestion
// API worker whose persons store runs in shadow mode, so the Postgres backend
// produces clickhouse_person_distinct_id rows and person_merge_events the way
// the pipeline does in production, while identity applies the same writes
// and personhog-publisher drains its outbox to per-run topics.
//
// The feeds are compared by end state, not message by message: the two
// backends can take different paths to the same place, and versions,
// timestamps, counts and order are each backend's own. clickhouse_person is
// not compared, the publisher does not project it.
import { ConsumerGlobalConfig, KafkaConsumer, LibrdKafkaError, Message, Metadata, WatermarkOffsets } from 'node-rdkafka'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { Pool } from 'pg'

import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_FLAG_EVALUATIONS,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_CLICKHOUSE_TOPHOG,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_LOG_ENTRIES,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_MERGE_EVENTS,
    KAFKA_REALTIME_ONLY_EVENTS_JSON,
} from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { uuidFromDistinctId } from '~/ingestion/common/persons/person-uuid'
import { Hub } from '~/types'

import { waitForExpect } from '../helpers/expectations'
import { DEFAULT_TEAM, EventBuilder, createKafkaMessage } from '../helpers/ingestion-e2e'
import { TEST_KAFKA_TOPICS, createKafkaTestTopicName, deleteKafkaTopics, ensureKafkaTopics } from '../helpers/kafka'
import { ServiceProcess, getFreePort, getFreeWorkerPort } from '../helpers/service-process'
import { createOrganization, createTeam } from '../helpers/sql'

jest.setTimeout(300_000)

const REPO_ROOT = path.resolve(__dirname, '../../..')
const NODEJS_ROOT = path.join(REPO_ROOT, 'nodejs')
const RUST_ROOT = path.join(REPO_ROOT, 'rust')
// Built binaries, not `cargo run`: nothing may compile under the test's clock.
const RUST_BIN_DIR = path.join(process.env.CARGO_TARGET_DIR ?? path.join(RUST_ROOT, 'target'), 'debug')
const HARNESS_BINARY = path.join(RUST_BIN_DIR, 'personhog-test-harness')
const ETCD_ENDPOINTS = process.env.PERSONHOG_E2E_ETCD_ENDPOINTS ?? 'http://localhost:2379'
// The table set the stack runs on; identity pairs the outbox with it.
const PG_TARGET_TABLE = 'personhog_person_tmp'
const OUTBOX_TABLE = 'person_publish_outbox_tmp'
// The worker serves its WorkerIngest stream on its HTTP port plus this
// offset; the Rust consumer derives the stream address the same way.
const GRPC_PORT_OFFSET = 1
const STACK_READY_TIMEOUT_MS = 180_000
// The stack stops a dozen services and deletes its topics on the way out.
const STACK_STOP_GRACE_MS = 60_000
const SETTLE_TIMEOUT_MS = 30_000
const FEED_CONVERGENCE_TIMEOUT_MS = 30_000
const TOPIC_READ_TIMEOUT_MS = 30_000
// The harness runs the monitor with a 15 s grace; the rest is margin.
const MONITOR_SETTLE_TIMEOUT_MS = 60_000
/** Outcomes that are not a disagreement: a stub is one feed's own path to the result. */
const MONITOR_AGREEMENTS = new Set(['agree', 'node_stub', 'personhog_stub', 'same', 'expected'])
const MONITOR_FAULTS = new Set([
    'personhog_parity_version_ties_total',
    'personhog_parity_merge_conflicts_total',
    'personhog_parity_decode_failures_total',
    'personhog_parity_overflow_evictions_total',
    'personhog_parity_warmup_evictions_total',
])

/** The ready line the harness's `stack` subcommand writes. */
interface StackReady {
    router_addr: string
    identity_addr: string
    changelog_topic: string
    distinct_ids_topic: string
    merge_events_topic: string
    monitor_addr: string
    log_dir: string
}

interface MetricSample {
    name: string
    labels: Record<string, string>
    value: number
}

interface DistinctIdRow {
    person_id: string
    team_id: number
    distinct_id: string
    version: number
    is_deleted: number
}

interface MergeEvent {
    team_id: number
    old_person_uuid: string
    new_person_uuid: string
}

interface FeedTopics {
    distinctIds: string
    mergeEvents: string
}

interface Mapping {
    personUuid: string
    isDeleted: boolean
}

/** The end state a consumer of a feed is left with. */
interface FeedState {
    /** The highest-version row per distinct id. */
    mappings: Record<string, Mapping>
    /** Every person the feed named, followed through its merge events to the one holding its state at the end. */
    survivors: Record<string, string>
}

type TestEvent = ReturnType<EventBuilder['build']>
type Register = (service: ServiceProcess) => void

describe('personhog kafka parity (e2e)', () => {
    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let stack: ServiceProcess | undefined
    let workers: ServiceProcess[] = []
    let workerUrl: string
    let monitorUrl: string
    let readyDir: string
    let inputTopic: string
    /** Every topic this run created, the stack's included, deleted at the end. */
    let ownTopics: string[] = []
    let nodeTopics: FeedTopics
    let personhogTopics: FeedTopics
    let personsDb: Pool
    let teamId: number
    let token: string

    const services = (): ServiceProcess[] => (stack ? [stack, ...workers] : workers)

    // Distinct ids are unique per run: the personhog side writes shared
    // tables, so a fixed id would meet a person a previous run made.
    const runTag = new UUIDT().toString().slice(0, 13)
    const id = (name: string): string => `kafka-parity-${runTag}-${name}`
    const personUuid = (distinctId: string): string => uuidFromDistinctId(teamId, distinctId)
    const live = (distinctId: string): Mapping => ({ personUuid: personUuid(distinctId), isDeleted: false })

    const event = (name: string, distinctId: string, properties: Record<string, unknown> = {}): TestEvent =>
        new EventBuilder({ ...DEFAULT_TEAM, id: teamId, api_token: token }, distinctId)
            .withEvent(name)
            .withProperties(properties)
            .build()
    const pageview = (distinctId: string): TestEvent => event('$pageview', distinctId)
    const identify = (distinctId: string, anonDistinctId?: string): TestEvent =>
        event('$identify', distinctId, anonDistinctId ? { $anon_distinct_id: anonDistinctId } : {})

    const send = async (...events: TestEvent[]): Promise<void> => {
        for (const entry of events) {
            const message = createKafkaMessage(entry, token)
            // Capture sets a uuid header; the consumer reads it before the body.
            const headers = [...(message.headers ?? []), { uuid: Buffer.from(entry.uuid ?? '') }]
            await kafkaProducer.produce({
                topic: inputTopic,
                key: message.key?.toString() ?? null,
                value: message.value ?? null,
                headers: Object.fromEntries(
                    headers.flatMap((header) => Object.entries(header).map(([name, value]) => [name, value.toString()]))
                ),
            })
        }
        await kafkaProducer.flush()
    }

    const feedState = async (topics: FeedTopics): Promise<FeedState> =>
        foldFeed(
            await readTopic(hub.KAFKA_HOSTS, topics.distinctIds),
            await readTopic(hub.KAFKA_HOSTS, topics.mergeEvents),
            teamId
        )

    const serviceLogs = (): string =>
        services()
            .map((service) => service.getOutput().slice(-6_000))
            .join('\n')

    /**
     * Gives up at once when a spawned service has exited, since nothing
     * changes after that, and attaches the services' logs to a failure: they
     * are subprocesses, so those logs are the only trace.
     */
    const pollUntil = async (check: () => Promise<void>, timeoutMs: number): Promise<void> => {
        const deadline = Date.now() + timeoutMs
        for (;;) {
            try {
                await check()
                return
            } catch (error) {
                const exit = services()
                    .map((service) => service.exitInfo())
                    .find((info) => info !== null)
                if (exit) {
                    throw new Error(
                        `a service exited (${exit.exitCode ?? exit.signal}) while waiting:\n${exit.output.slice(-6_000)}`
                    )
                }
                if (Date.now() > deadline) {
                    throw new Error(`${error instanceof Error ? error.message : String(error)}\n\n${serviceLogs()}`)
                }
                await new Promise((resolve) => setTimeout(resolve, 500))
            }
        }
    }

    /**
     * Waits for both feeds to hold what an earlier step produced. The worker
     * runs a batch's distinct ids concurrently, so a scenario whose premise
     * is "this person exists" has to see the person land before it sends the
     * event that depends on it, and on both sides, so a swallowed shadow
     * write cannot turn the next step into a different scenario.
     */
    const awaitBoth = (check: (feed: FeedState) => void): Promise<void> =>
        pollUntil(async () => {
            check(await feedState(nodeTopics))
            check(await feedState(personhogTopics))
        }, SETTLE_TIMEOUT_MS)

    /**
     * Both feeds fill asynchronously, the personhog one behind the outbox
     * drain, so the end states are polled until they agree and the last
     * mismatch is what a timeout reports.
     */
    const expectFeedParity = async (settled: (feed: FeedState) => void): Promise<FeedState> => {
        await awaitBoth(settled)
        let node!: FeedState
        await pollUntil(async () => {
            node = await feedState(nodeTopics)
            expectSameEndState(await feedState(personhogTopics), node)
        }, FEED_CONVERGENCE_TIMEOUT_MS)
        return node
    }

    beforeAll(async () => {
        hub = await createHub({})
        kafkaProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        inputTopic = createKafkaTestTopicName(KAFKA_EVENTS_PLUGIN_INGESTION)
        const outputTopics = {
            events: createKafkaTestTopicName(KAFKA_EVENTS_JSON),
            persons: createKafkaTestTopicName(KAFKA_PERSON),
            distinctIds: createKafkaTestTopicName(KAFKA_PERSON_DISTINCT_ID),
            warnings: createKafkaTestTopicName(KAFKA_INGESTION_WARNINGS),
            mergeEvents: createKafkaTestTopicName(KAFKA_PERSON_MERGE_EVENTS),
        }
        nodeTopics = { distinctIds: outputTopics.distinctIds, mergeEvents: outputTopics.mergeEvents }
        ownTopics = [inputTopic, ...Object.values(outputTopics)]
        await ensureKafkaTopics([...TEST_KAFKA_TOPICS, ...ownTopics])

        const organizationId = await createOrganization(hub.postgres)
        token = `kafka-parity-${runTag}`
        teamId = await createTeam(hub.postgres, organizationId, token)
        personsDb = new Pool({ connectionString: hub.PERSONS_DATABASE_URL, max: 2 })

        // Each service registers as soon as it is spawned, so one that never
        // becomes ready is still stopped in afterAll.
        readyDir = mkdtempSync(path.join(tmpdir(), 'personhog-kafka-parity-'))
        const ready = await startPersonhogStack(hub, path.join(readyDir, 'ready.json'), nodeTopics, (service) => {
            stack = service
        })
        ownTopics.push(ready.changelog_topic, ready.distinct_ids_topic, ready.merge_events_topic)
        personhogTopics = { distinctIds: ready.distinct_ids_topic, mergeEvents: ready.merge_events_topic }
        monitorUrl = `http://${ready.monitor_addr}`

        workerUrl = await startNodeIngestionApiWorker(
            hub,
            {
                INGESTION_CONSUMER_CONSUME_TOPIC: inputTopic,
                INGESTION_OUTPUT_EVENTS_TOPIC: outputTopics.events,
                INGESTION_OUTPUT_PERSONS_TOPIC: outputTopics.persons,
                INGESTION_OUTPUT_PERSON_DISTINCT_IDS_TOPIC: outputTopics.distinctIds,
                INGESTION_OUTPUT_INGESTION_WARNINGS_TOPIC: outputTopics.warnings,
                INGESTION_OUTPUT_PERSON_MERGE_EVENTS_TOPIC: outputTopics.mergeEvents,
                PERSONS_STORE_MODE: 'shadow',
                PERSONHOG_ADDR: ready.router_addr,
                PERSONHOG_IDENTITY_ADDR: ready.identity_addr,
                PERSON_MERGE_EVENTS_ENABLED: 'true',
                // ensureKafkaTopics creates one-partition topics, and Node
                // partitions merge events itself.
                PERSON_MERGE_EVENTS_PARTITION_COUNT: '1',
                PERSON_MERGE_EVENTS_TEAM_ALLOWLIST: '*',
            },
            (service) => workers.push(service)
        )
        await startRustIngestionConsumer(hub, inputTopic, workerUrl, (service) => workers.push(service))
    }, 600_000)

    afterAll(async () => {
        // The consumer first, so no batch is mid-flight when its worker goes;
        // the stack last, with time to tear itself down.
        for (const worker of workers.reverse()) {
            await worker.stop()
        }
        workers = []
        await stack?.stop(STACK_STOP_GRACE_MS)
        stack = undefined
        await Promise.allSettled([personsDb?.end(), kafkaProducer?.disconnect()])
        // The stack deletes its own topics on a clean exit; this also covers
        // one that was cut short, and the broker counts every partition.
        await deleteKafkaTopics(ownTopics)
        if (readyDir) {
            rmSync(readyDir, { recursive: true, force: true })
        }
        if (hub) {
            await closeHub(hub)
        }
    })

    it('a new distinct id lands as one person on both feeds', async () => {
        const visitor = id('visitor')

        await send(pageview(visitor))

        await expectFeedParity((feed) => {
            expect(feed.mappings[visitor]).toEqual(live(visitor))
        })
    })

    it('an identify of two unseen ids births one person on both feeds', async () => {
        const anon = id('birth-anon')
        const user = id('birth-user')

        await send(identify(user, anon))

        await expectFeedParity((feed) => {
            expect(feed.mappings[user]).toEqual(live(user))
            expect(feed.mappings[anon]).toEqual(live(user))
        })
    })

    it.each([
        ['$identify', (existing: string, unseen: string) => identify(unseen, existing)],
        ['$create_alias', (existing: string, unseen: string) => event('$create_alias', existing, { alias: unseen })],
    ])('%s attaches an unseen id to an existing person on both feeds', async (name, attach) => {
        const existing = id(`${name}-existing`)
        const unseen = id(`${name}-unseen`)
        await send(pageview(existing))
        await awaitBoth((feed) => expect(feed.mappings[existing]).toEqual(live(existing)))

        await send(attach(existing, unseen))

        await expectFeedParity((feed) => {
            expect(feed.mappings[unseen]).toEqual(live(existing))
        })
    })

    it('identifies that merge existing persons leave each merged person resolving to the survivor', async () => {
        const user = id('merge-user')
        const anons = [id('merge-anon-1'), id('merge-anon-2')]
        await send(pageview(user), ...anons.map(pageview))
        await awaitBoth((feed) => {
            for (const distinctId of [user, ...anons]) {
                expect(feed.mappings[distinctId]).toEqual(live(distinctId))
            }
        })

        await send(identify(user, anons[0]))
        await awaitBoth((feed) => expect(feed.survivors[personUuid(anons[0])]).toBe(personUuid(user)))
        await send(identify(user, anons[1]))

        const { mappings } = await expectFeedParity((feed) => {
            for (const anon of anons) {
                expect(feed.survivors[personUuid(anon)]).toBe(personUuid(user))
            }
        })
        for (const anon of anons) {
            expect(mappings[anon]).toEqual(live(user))
        }
    })

    it('a merge dangerously of two identified persons moves the alias to the keeper on both feeds', async () => {
        const keeper = id('dangerous-keeper')
        const alias = id('dangerous-alias')
        // An identify with an anonymous id is what marks a person identified;
        // without one the merge below would be an ordinary one.
        await send(identify(keeper, id('dangerous-keeper-anon')), identify(alias, id('dangerous-alias-anon')))
        await awaitBoth((feed) => {
            expect(feed.mappings[keeper]).toEqual(live(keeper))
            expect(feed.mappings[alias]).toEqual(live(alias))
        })

        await send(event('$merge_dangerously', keeper, { alias }))

        const { mappings } = await expectFeedParity((feed) => {
            expect(feed.survivors[personUuid(alias)]).toBe(personUuid(keeper))
        })
        expect(mappings[alias]).toEqual(live(keeper))
    })

    it('a repeated identify adds no merge on either feed', async () => {
        const anon = id('again-anon')
        const user = id('again-user')
        const marker = id('again-marker')
        await send(pageview(anon), pageview(user))
        await awaitBoth((feed) => {
            expect(feed.mappings[anon]).toEqual(live(anon))
            expect(feed.mappings[user]).toEqual(live(user))
        })
        await send(identify(user, anon))
        const before = await expectFeedParity((feed) => {
            expect(feed.survivors[personUuid(anon)]).toBe(personUuid(user))
        })

        // The second identify finds both ids on one person. The alias after
        // it shares the user's lane, so its row landing means the identify ran.
        await send(identify(user, anon), event('$create_alias', user, { alias: marker }))

        const after = await expectFeedParity((feed) => {
            expect(feed.mappings[marker]).toEqual(live(user))
        })
        expect(after.survivors).toEqual(before.survivors)
        expect(after.mappings).toEqual({ ...before.mappings, [marker]: live(user) })
    })

    it('an identify through an identified anonymous id gives the unseen id its own person on both feeds', async () => {
        const anon = id('refuse-anon')
        const user = id('refuse-user')
        const other = id('refuse-other')
        await send(pageview(anon), pageview(user))
        await awaitBoth((feed) => {
            expect(feed.mappings[anon]).toEqual(live(anon))
            expect(feed.mappings[user]).toEqual(live(user))
        })
        await send(identify(user, anon))
        const before = await expectFeedParity((feed) => {
            expect(feed.survivors[personUuid(anon)]).toBe(personUuid(user))
        })

        // The user is identified now, so the unseen id may not join its
        // person: both backends refuse the merge and create a person for it.
        await send(identify(other, user))

        const after = await expectFeedParity((feed) => {
            expect(feed.mappings[other]).toEqual(live(other))
        })
        expect(after.survivors).toEqual({ ...before.survivors, [personUuid(other)]: personUuid(other) })
        expect(after.mappings[user]).toEqual(before.mappings[user])
    })

    it('the outbox drains and the feeds still agree', async () => {
        await waitForExpect(
            async () => {
                const { rows } = await personsDb.query<{ pending: string }>(
                    `SELECT count(*)::text AS pending FROM ${OUTBOX_TABLE} WHERE team_id = $1`,
                    [teamId]
                )
                expect(rows[0].pending).toBe('0')
            },
            TOPIC_READ_TIMEOUT_MS,
            250
        )

        await expectFeedParity(() => {})
    })

    it('every shadow write reached personhog', async () => {
        // Shadow mode swallows a failed personhog write by design; the
        // comparison above tolerates the different path such a failure can
        // leave, so the counter is the only place it shows.
        const response = await workers[0].request(`${workerUrl}/_metrics`, { method: 'GET' })
        expect(response.statusCode).toBe(200)
        const errors = response.body
            .split('\n')
            .filter((line) => line.startsWith('personhog_store_shadow_errors_total'))
            .map((line) => Number(line.trim().split(/\s+/).pop()))
            .reduce((sum, value) => sum + value, 0)
        expect(errors).toBe(0)
    })

    it('the parity monitor settled every entry of both feeds as agreement', async () => {
        // A key settles at least once, so agreement below the fold's size
        // means the monitor read a different topic than the fold did. The
        // counts are polled with the pending gauges: a reader still behind
        // the last rows reports nothing pending before they arrive.
        const node = await feedState(nodeTopics)
        const personhog = await feedState(personhogTopics)
        const sharedMerges = Object.entries(node.survivors).filter(
            ([person, survivor]) => survivor !== person && person in personhog.survivors
        ).length
        let samples!: MetricSample[]
        await pollUntil(async () => {
            const response = await stack!.request(`${monitorUrl}/metrics`, { method: 'GET' })
            expect(response.statusCode).toBe(200)
            samples = parsePrometheus(response.body)
            expect(metric(samples, 'personhog_parity_pending_entries', { kind: 'mappings' })).toBe(0)
            expect(metric(samples, 'personhog_parity_pending_entries', { kind: 'merges' })).toBe(0)
            expect(
                metric(samples, 'personhog_parity_settled_mappings_total', { outcome: 'agree' })
            ).toBeGreaterThanOrEqual(Object.keys(node.mappings).length)
            expect(
                metric(samples, 'personhog_parity_settled_merges_total', { outcome: 'agree' })
            ).toBeGreaterThanOrEqual(sharedMerges)
        }, MONITOR_SETTLE_TIMEOUT_MS)

        expect(monitorDisagreements(samples)).toEqual([])
    })
})

function parsePrometheus(body: string): MetricSample[] {
    const samples: MetricSample[] = []
    for (const line of body.split('\n')) {
        const match = /^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+(\S+)/.exec(line)
        if (!match) {
            continue
        }
        const labels: Record<string, string> = {}
        for (const pair of (match[2] ?? '').matchAll(/([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"/g)) {
            labels[pair[1]] = pair[2]
        }
        samples.push({ name: match[1], labels, value: Number(match[3]) })
    }
    return samples
}

function metric(samples: MetricSample[], name: string, labels: Record<string, string>): number | undefined {
    return samples.find(
        (sample) => sample.name === name && Object.entries(labels).every(([key, value]) => sample.labels[key] === value)
    )?.value
}

function monitorDisagreements(samples: MetricSample[]): string[] {
    return samples
        .filter(
            ({ name, labels, value }) =>
                value > 0 &&
                name.startsWith('personhog_parity_') &&
                (MONITOR_FAULTS.has(name) || ('outcome' in labels && !MONITOR_AGREEMENTS.has(labels.outcome)))
        )
        .map(({ name, labels, value }) => `${name}${JSON.stringify(labels)} ${value}`)
}

/**
 * The same end state on both feeds. A person only one feed ever named is
 * that feed's own path to the result, a stub the other backend never made
 * and then merged away, and it carries no state on the other side; every
 * person both feeds named has to end in the same place.
 */
function expectSameEndState(personhog: FeedState, node: FeedState): void {
    expect(personhog.mappings).toEqual(node.mappings)
    const shared = Object.keys(node.survivors).filter((person) => person in personhog.survivors)
    const pick = (survivors: Record<string, string>): Record<string, string> =>
        Object.fromEntries(shared.map((person) => [person, survivors[person]]))
    expect(pick(personhog.survivors)).toEqual(pick(node.survivors))
    for (const feed of [node, personhog]) {
        expectEveryPersonAccountedFor(feed)
    }
}

/**
 * A person that holds no live distinct id at the end must have been merged
 * into one that does, and a live distinct id must not point at a person
 * that was merged away.
 */
function expectEveryPersonAccountedFor(feed: FeedState): void {
    const liveMappings = Object.values(feed.mappings).filter((mapping) => !mapping.isDeleted)
    const holders = new Set(liveMappings.map((mapping) => mapping.personUuid))
    const unaccounted = Object.entries(feed.survivors)
        .filter(([, survivor]) => !holders.has(survivor))
        .map(([person, survivor]) => `${person} -> ${survivor}`)
    expect(unaccounted).toEqual([])
    const stale = liveMappings
        .filter((mapping) => feed.survivors[mapping.personUuid] !== mapping.personUuid)
        .map((mapping) => `${mapping.personUuid} -> ${feed.survivors[mapping.personUuid]}`)
    expect(stale).toEqual([])
}

async function startPersonhogStack(
    hub: Hub,
    readyFile: string,
    nodeTopics: FeedTopics,
    register: Register
): Promise<StackReady> {
    if (!existsSync(HARNESS_BINARY)) {
        throw new Error(`${HARNESS_BINARY} is missing; build the personhog stack and harness first`)
    }
    const service = new ServiceProcess(
        'personhog-stack',
        HARNESS_BINARY,
        [
            'stack',
            '--publish',
            // The stack assigns the Node topics (created above) before it
            // writes the ready file, so no event of this run predates them.
            '--monitor',
            '--monitor-node-distinct-ids-topic',
            nodeTopics.distinctIds,
            '--monitor-node-merge-events-topic',
            nodeTopics.mergeEvents,
            '--bin-dir',
            RUST_BIN_DIR,
            '--pg-target-table',
            PG_TARGET_TABLE,
            '--persons-db-url',
            hub.PERSONS_DATABASE_URL,
            '--kafka-hosts',
            hub.KAFKA_HOSTS,
            '--etcd-endpoints',
            ETCD_ENDPOINTS,
            '--ready-file',
            readyFile,
        ],
        { cwd: RUST_ROOT, env: serviceProcessEnv() }
    )
    register(service)
    const deadline = Date.now() + STACK_READY_TIMEOUT_MS
    while (!existsSync(readyFile)) {
        const exit = await service.waitForExit(250).catch(() => null)
        if (exit) {
            throw new Error(
                `personhog stack exited before it was ready (${exit.exitCode ?? exit.signal}):\n${exit.output}`
            )
        }
        if (Date.now() > deadline) {
            throw new Error(`personhog stack not ready within ${STACK_READY_TIMEOUT_MS}ms:\n${service.getOutput()}`)
        }
    }
    const ready = parseJSON(readFileSync(readyFile, 'utf8')) as StackReady
    if (!ready.monitor_addr) {
        throw new Error(`the stack reported no monitor address; is ${HARNESS_BINARY} built from this branch?`)
    }
    return ready
}

async function startNodeIngestionApiWorker(
    hub: Hub,
    extraEnv: Record<string, string>,
    register: Register
): Promise<string> {
    const port = await getFreeWorkerPort(GRPC_PORT_OFFSET)
    const service = new ServiceProcess('node-worker', 'pnpm', ['exec', 'tsx', 'src/index.ts'], {
        cwd: NODEJS_ROOT,
        env: {
            ...serviceProcessEnv(),
            ...dependencyEnv(hub),
            NODE_ENV: 'dev',
            PLUGIN_SERVER_MODE: 'ingestion-api',
            HTTP_SERVER_PORT: port.toString(),
            INGESTION_API_GRPC_PORT: (port + GRPC_PORT_OFFSET).toString(),
            OTEL_SDK_DISABLED: 'true',
            DISABLE_OPENTELEMETRY_TRACING: 'true',
            LOG_LEVEL: 'warn',
            INGESTION_WORKER_CONCURRENT_BATCHES: '1',
            PROPERTY_DEFS_WRITE_DISABLED: 'true',
            PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS: '',
            // The worker verifies every output topic at startup, so the ones
            // this test never reads point at the shared test topics.
            INGESTION_CONSUMER_DLQ_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
            INGESTION_CONSUMER_OVERFLOW_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            INGESTION_OUTPUT_DLQ_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
            INGESTION_OUTPUT_OVERFLOW_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            INGESTION_OUTPUT_ASYNC_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
            INGESTION_OUTPUT_AI_EVENTS_TOPIC: KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
            INGESTION_OUTPUT_FLAG_EVALUATIONS_TOPIC: KAFKA_CLICKHOUSE_FLAG_EVALUATIONS,
            INGESTION_OUTPUT_REALTIME_ONLY_EVENTS_TOPIC: KAFKA_REALTIME_ONLY_EVENTS_JSON,
            INGESTION_OUTPUT_HEATMAPS_TOPIC: KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
            INGESTION_OUTPUT_GROUPS_TOPIC: KAFKA_GROUPS,
            INGESTION_OUTPUT_APP_METRICS_TOPIC: KAFKA_APP_METRICS_2,
            INGESTION_OUTPUT_LOG_ENTRIES_TOPIC: KAFKA_LOG_ENTRIES,
            INGESTION_OUTPUT_TOPHOG_TOPIC: KAFKA_CLICKHOUSE_TOPHOG,
            ...extraEnv,
        },
    })
    register(service)
    const url = `http://127.0.0.1:${port}`
    await service.waitForHttpOk(`${url}/_ready`)
    return url
}

async function startRustIngestionConsumer(
    hub: Hub,
    inputTopic: string,
    workerUrl: string,
    register: Register
): Promise<void> {
    const metricsPort = await getFreePort()
    const service = new ServiceProcess('rust-consumer', path.join(RUST_BIN_DIR, 'ingestion-consumer'), [], {
        cwd: RUST_ROOT,
        env: {
            ...serviceProcessEnv(),
            RUST_LOG: 'info',
            KAFKA_HOSTS: hub.KAFKA_HOSTS,
            INGESTION_CONSUMER_CONSUME_TOPIC: inputTopic,
            INGESTION_CONSUMER_GROUP_ID: `personhog-kafka-parity-${Date.now()}-${Math.random().toString(16).slice(2)}`,
            // Rust's generic KAFKA_CONSUMER_* parser maps this name to the invalid rdkafka key "offset.reset".
            KAFKA_CONSUMER_OFFSET_RESET: undefined,
            KAFKA_CONSUMER_AUTO_OFFSET_RESET: 'earliest',
            CONSUMER_BATCH_SIZE: '10',
            CONSUMER_BATCH_TIMEOUT_MS: '1000',
            CONSUMER_MAX_BACKGROUND_TASKS: '1',
            INGESTION_WORKER_CONCURRENT_BATCHES: '1',
            WORKER_ADDRESSES: workerUrl,
            INGESTION_WORKER_GRPC_PORT_OFFSET: GRPC_PORT_OFFSET.toString(),
            BIND_HOST: '127.0.0.1',
            BIND_PORT: metricsPort.toString(),
            EXPORT_PROMETHEUS: 'true',
        },
    })
    register(service)
    await service.waitForHttpOk(`http://127.0.0.1:${metricsPort}/_readiness`)
}

function serviceProcessEnv(): NodeJS.ProcessEnv {
    const env = { ...process.env }
    delete env.NODE_OPTIONS
    delete env.VSCODE_INSPECTOR_OPTIONS
    // Inherited from an editor's extension host, it makes node-gyp-build
    // look for Electron builds of native modules the worker loads.
    delete env.ELECTRON_RUN_AS_NODE
    return env
}

/** The hub resolved these from the environment; the worker must see the same ones. */
function dependencyEnv(hub: Hub): NodeJS.ProcessEnv {
    return {
        DATABASE_URL: hub.DATABASE_URL,
        PERSONS_DATABASE_URL: hub.PERSONS_DATABASE_URL,
        PERSONS_READONLY_DATABASE_URL: hub.PERSONS_READONLY_DATABASE_URL,
        BEHAVIORAL_COHORTS_DATABASE_URL: hub.BEHAVIORAL_COHORTS_DATABASE_URL,
        KAFKA_HOSTS: hub.KAFKA_HOSTS,
        KAFKA_PRODUCER_METADATA_BROKER_LIST: hub.KAFKA_HOSTS,
        KAFKA_WARPSTREAM_PRODUCER_METADATA_BROKER_LIST: hub.KAFKA_HOSTS,
        KAFKA_INGESTION_PRODUCER_METADATA_BROKER_LIST: hub.KAFKA_HOSTS,
        REDIS_URL: hub.REDIS_URL,
        SITE_URL: 'https://example.com',
    }
}

function foldFeed(distinctIdRows: Buffer[], mergeEvents: Buffer[], teamId: number): FeedState {
    const latest = new Map<string, DistinctIdRow>()
    const persons = new Set<string>()
    for (const value of distinctIdRows) {
        const row = parseJSON(value.toString()) as DistinctIdRow
        if (row.team_id !== teamId) {
            continue
        }
        persons.add(row.person_id)
        const seen = latest.get(row.distinct_id)
        if (
            seen &&
            seen.version === row.version &&
            (seen.person_id !== row.person_id || seen.is_deleted !== row.is_deleted)
        ) {
            // A ReplacingMergeTree keeps either of two rows at one version, so
            // such a feed has no single final state to compare.
            throw new Error(
                `two rows at version ${row.version} for ${row.distinct_id}: ${JSON.stringify(seen)} and ${JSON.stringify(row)}`
            )
        }
        if (!seen || row.version > seen.version) {
            latest.set(row.distinct_id, row)
        }
    }

    const mergedInto = new Map<string, string>()
    for (const value of mergeEvents) {
        const merge = parseJSON(value.toString()) as MergeEvent
        if (merge.team_id !== teamId) {
            continue
        }
        const already = mergedInto.get(merge.old_person_uuid)
        if (already && already !== merge.new_person_uuid) {
            throw new Error(`${merge.old_person_uuid} merged into both ${already} and ${merge.new_person_uuid}`)
        }
        mergedInto.set(merge.old_person_uuid, merge.new_person_uuid)
        persons.add(merge.old_person_uuid)
        persons.add(merge.new_person_uuid)
    }

    return {
        mappings: Object.fromEntries(
            [...latest.entries()]
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([distinctId, row]) => [
                    distinctId,
                    { personUuid: row.person_id, isDeleted: row.is_deleted === 1 },
                ])
        ),
        survivors: Object.fromEntries([...persons].sort().map((person) => [person, survivorOf(person, mergedInto)])),
    }
}

function survivorOf(person: string, mergedInto: Map<string, string>): string {
    const visited = new Set<string>()
    let current = person
    while (mergedInto.has(current)) {
        if (visited.has(current)) {
            throw new Error(`merge events loop through ${current}`)
        }
        visited.add(current)
        current = mergedInto.get(current)!
    }
    return current
}

/**
 * Every message on the topic up to each partition's high watermark at the
 * time of the call. Per partition, not by count: a producer still writing
 * to one partition must not stand in for messages owed by another.
 */
async function readTopic(kafkaHosts: string, topic: string): Promise<Buffer[]> {
    const consumer = new KafkaConsumer(
        {
            'client.id': 'personhog-kafka-parity-e2e',
            'group.id': `personhog-kafka-parity-${Date.now()}-${Math.random().toString(16).slice(2)}`,
            'metadata.broker.list': kafkaHosts,
            'enable.auto.commit': false,
            'auto.offset.reset': 'earliest',
            log_level: 4,
        } as ConsumerGlobalConfig,
        {}
    )
    await new Promise<void>((resolve, reject) => {
        consumer.once('ready', () => resolve())
        consumer.once('event.error', (error) => reject(error))
        consumer.connect()
    })
    try {
        const partitions = await topicPartitions(consumer, topic)
        const watermarks = await Promise.all(
            partitions.map(async (partition) => ({
                partition,
                ...(await watermarkOffsets(consumer, topic, partition)),
            }))
        )
        const owed = new Map(
            watermarks
                .filter((entry) => entry.highOffset > entry.lowOffset)
                .map((entry) => [entry.partition, entry.highOffset - entry.lowOffset])
        )
        if (owed.size === 0) {
            return []
        }
        consumer.assign(
            watermarks
                .filter((entry) => owed.has(entry.partition))
                .map((entry) => ({ topic, partition: entry.partition, offset: entry.lowOffset }))
        )

        const values: Buffer[] = []
        const deadline = Date.now() + TOPIC_READ_TIMEOUT_MS
        while (owed.size > 0 && Date.now() < deadline) {
            // Exactly what is still owed: a larger ask makes the consumer
            // wait out its timeout instead of returning what it has.
            const messages = await consumeMessages(
                consumer,
                [...owed.values()].reduce((sum, left) => sum + left, 0)
            )
            if (messages.length === 0) {
                await new Promise((resolve) => setTimeout(resolve, 100))
            }
            for (const message of messages) {
                const left = owed.get(message.partition)
                if (left === undefined) {
                    continue
                }
                values.push(message.value ?? Buffer.alloc(0))
                if (left === 1) {
                    owed.delete(message.partition)
                } else {
                    owed.set(message.partition, left - 1)
                }
            }
        }
        if (owed.size > 0) {
            throw new Error(`partitions ${[...owed.keys()].join(', ')} of ${topic} did not reach their watermark`)
        }
        return values
    } finally {
        await new Promise<void>((resolve, reject) =>
            consumer.disconnect((error) => (error ? reject(error) : resolve()))
        )
    }
}

async function topicPartitions(consumer: KafkaConsumer, topic: string): Promise<number[]> {
    const metadata = await new Promise<Metadata>((resolve, reject) => {
        consumer.getMetadata({ topic, timeout: 10_000 }, (error: LibrdKafkaError, result: Metadata) =>
            error ? reject(error) : resolve(result)
        )
    })
    const found = metadata.topics.find((entry) => entry.name === topic)
    if (!found) {
        throw new Error(`Kafka topic ${topic} was not found in metadata`)
    }
    return found.partitions.map((partition) => partition.id)
}

async function watermarkOffsets(consumer: KafkaConsumer, topic: string, partition: number): Promise<WatermarkOffsets> {
    return await new Promise((resolve, reject) => {
        consumer.queryWatermarkOffsets(topic, partition, 10_000, (error: LibrdKafkaError, offsets: WatermarkOffsets) =>
            error ? reject(error) : resolve(offsets)
        )
    })
}

async function consumeMessages(consumer: KafkaConsumer, count: number): Promise<Message[]> {
    return await new Promise((resolve, reject) => {
        consumer.consume(count, (error, messages) => (error ? reject(error) : resolve(messages)))
    })
}
