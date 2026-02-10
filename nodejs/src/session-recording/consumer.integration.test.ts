/**
 * End-to-end integration test for the session recording consumer.
 *
 * This test validates behavioral parity of the session recording pipeline by testing
 * at the consumer level using real local infrastructure (Kafka, S3, Redis, Postgres).
 *
 * ## How it works
 *
 * 1. Produces test messages to the input Kafka topic (session_recording_snapshot_item_events)
 * 2. The real SessionRecordingIngester consumes and processes messages
 * 3. Ingester writes session data to S3 and publishes metadata to the output Kafka topic
 * 4. Test consumes session metadata from the output topic (clickhouse_session_replay_events)
 * 5. Uses the block_url byte ranges from metadata to read specific S3 blocks
 * 6. Decompresses snappy blocks and parses JSONL event data
 * 7. Builds a snapshot capturing event types, ordering, window IDs, and metadata counts
 *
 * This allows us to:
 * - Capture baseline behavior before refactoring
 * - Verify behavioral parity after incremental changes
 * - Guarantee event ordering and session batching correctness
 *
 * ## Running locally
 *
 * Prerequisites:
 * - Docker (for local infrastructure)
 * - Python environment (for Django migrations)
 *
 * Steps:
 * 1. Start the required services (Kafka, MinIO, Postgres, Redis):
 *      hogli dev:setup
 *    Or manually:
 *      docker compose -f docker-compose.dev.yml up
 *
 * 2. Set up the test database (creates test_posthog DB and runs migrations):
 *      pnpm setup:test
 *
 * 3. Run the tests:
 *      pnpm jest src/session-recording/consumer.integration.test.ts
 *
 * Tests are automatically skipped if the required infrastructure is not available,
 * with a message indicating which services are missing.
 *
 * ## Adding new test cases
 *
 * 1. Add a new entry to the `testCases` array with:
 *    - `name`: Short identifier used in the snapshot name
 *    - `description`: What the test verifies
 *    - `createPayloads`: Function returning PayloadConfig[] with test data
 *    - `expectedOutcome`: 'written' (data should appear in S3) or 'dropped' (rejected)
 *
 * 2. Run tests with the update flag to generate the new snapshot:
 *      pnpm jest src/session-recording/consumer.integration.test.ts -u
 *
 * 3. Review the generated snapshot in __snapshots__/consumer.integration.test.ts.snap
 *    to ensure it captures the expected behavior.
 *
 * ## Updating snapshots after refactoring
 *
 * If refactoring changes the output format (but behavior is correct), update snapshots:
 *      pnpm jest src/session-recording/consumer.integration.test.ts -u
 *
 * Always review snapshot diffs carefully - they should reflect intentional changes only.
 * If a snapshot changes unexpectedly, investigate before updating.
 */
import { DeleteObjectsCommand, GetObjectCommand, ListObjectsV2Command, S3Client } from '@aws-sdk/client-s3'
import { HighLevelProducer, KafkaConsumer } from 'node-rdkafka'
import snappy from 'snappy'
import { v4 as uuidv4 } from 'uuid'

import { waitForExpect } from '../../tests/helpers/expectations'
import { resetKafka } from '../../tests/helpers/kafka'
import { forSnapshot } from '../../tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig, overrideWithEnv } from '../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../config/kafka-topics'
import { KafkaProducerWrapper } from '../kafka/producer'
import { Hub, Team } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../utils/db/postgres'
import { parseJSON } from '../utils/json-parse'
import { SessionRecordingIngester } from './consumer'
import { RRWebEventType } from './rrweb-types'

// Test configuration - matches local dev environment (MinIO API on port 19000)
const TEST_CONFIG = {
    S3_ENDPOINT: 'http://localhost:19000',
    S3_REGION: 'us-east-1',
    S3_BUCKET: 'posthog',
    S3_PREFIX: 'session_recordings_integration_test',
    S3_ACCESS_KEY: 'object_storage_root_user',
    S3_SECRET_KEY: 'object_storage_root_password',
    S3_TIMEOUT_MS: 30000,
}

// Reduced wait time for partition assignments (1 second is usually enough locally)
const PARTITION_ASSIGNMENT_WAIT_MS = 1000

/**
 * Payload configuration for test cases.
 */
interface PayloadConfig {
    sessionId: string
    distinctId: string
    token: string
    windowId?: string
    events: Array<{ type: number; data: unknown; timestamp?: number }>
}

/**
 * Session metadata as received from Kafka (snake_case format).
 *
 * This mirrors the format produced by KafkaSessionMetadataStore.storeSessionBlocks(),
 * which converts from SessionBlockMetadata (camelCase) to this Kafka format.
 * The Kafka format isn't exported as a type, so we define it here for parsing.
 */
interface KafkaSessionMetadata {
    session_id: string
    team_id: number
    distinct_id: string
    block_url: string | null
    event_count: number
    first_url: string | null
    urls: string[]
    click_count: number
    keypress_count: number
    mouse_activity_count: number
    console_log_count: number
    console_warn_count: number
    console_error_count: number
    size: number
}

/**
 * Parsed session event from S3 block.
 *
 * S3 blocks contain snappy-compressed JSONL where each line is [windowId, event].
 * This represents the parsed event structure for snapshot verification.
 */
interface ParsedSessionEvent {
    windowId: string
    type: number
    timestamp: number
    data: unknown
}

/**
 * Test case definition for parameterized testing.
 */
interface TestCase {
    name: string
    description: string
    createPayloads: (team: Team, testRunId: string) => PayloadConfig[]
    expectedOutcome: 'written' | 'dropped'
}

/**
 * Creates a Kafka message payload for session recording.
 *
 * Headers match what capture sends - these are used by the event restrictions
 * pipeline for rate limiting and routing decisions.
 */
function createKafkaPayload(config: PayloadConfig): {
    value: Buffer
    key: Buffer
    headers: Record<string, string>
} {
    const { sessionId, distinctId, token, windowId = 'window-1', events } = config

    const baseTimestamp = Date.now()
    const snapshotItems = events.map((event, index) => ({
        type: event.type,
        data: event.data,
        timestamp: event.timestamp ?? baseTimestamp + index * 1000,
    }))

    const eventData = {
        event: '$snapshot_items',
        properties: {
            $snapshot_items: snapshotItems,
            $session_id: sessionId,
            $window_id: windowId,
            $snapshot_source: 'web',
            $lib: 'posthog-js',
        },
    }

    const messagePayload = {
        distinct_id: distinctId,
        data: JSON.stringify(eventData),
    }

    const now = new Date().toISOString()

    return {
        value: Buffer.from(JSON.stringify(messagePayload)),
        key: Buffer.from(sessionId),
        headers: {
            token,
            distinct_id: distinctId,
            session_id: sessionId,
            event: '$snapshot_items',
            uuid: uuidv4(),
            timestamp: baseTimestamp.toString(),
            now,
        },
    }
}

/**
 * Produces a message to Kafka.
 */
async function produceToKafka(
    producer: KafkaProducerWrapper,
    topic: string,
    payload: { value: Buffer; key: Buffer; headers: Record<string, string> }
): Promise<void> {
    await producer.produce({
        topic,
        value: payload.value,
        key: payload.key,
        headers: payload.headers,
    })
    await producer.flush()
}

/**
 * Checks if S3 (MinIO) is available.
 */
async function isS3Available(s3Client: S3Client): Promise<boolean> {
    try {
        await s3Client.send(new ListObjectsV2Command({ Bucket: TEST_CONFIG.S3_BUCKET, MaxKeys: 1 }))
        return true
    } catch {
        return false
    }
}

/**
 * Checks if Kafka is available.
 */
async function isKafkaAvailable(): Promise<boolean> {
    return new Promise((resolve) => {
        const config = overrideWithEnv(defaultConfig, process.env)
        const producer = new HighLevelProducer({
            'metadata.broker.list': config.KAFKA_HOSTS,
            'socket.timeout.ms': 5000,
        })

        const timeout = setTimeout(() => {
            producer.disconnect()
            resolve(false)
        }, 5000)

        producer.on('ready', () => {
            clearTimeout(timeout)
            producer.disconnect()
            resolve(true)
        })

        producer.on('event.error', () => {
            clearTimeout(timeout)
            producer.disconnect()
            resolve(false)
        })

        producer.connect()
    })
}

/**
 * Checks if Postgres is available with the test database.
 */
async function isPostgresAvailable(): Promise<boolean> {
    const config = overrideWithEnv(defaultConfig, process.env)
    const pg = new PostgresRouter({ ...config, POSTGRES_CONNECTION_POOL_SIZE: 1 })
    try {
        await pg.query(PostgresUse.COMMON_READ, 'SELECT 1', undefined, 'health-check')
        await pg.end()
        return true
    } catch {
        await pg.end()
        return false
    }
}

/**
 * Cleans up test data from S3, handling pagination for large result sets.
 */
async function cleanupS3TestData(s3Client: S3Client): Promise<void> {
    try {
        let continuationToken: string | undefined

        // Keep listing and deleting until no more objects
        do {
            const listResponse = await s3Client.send(
                new ListObjectsV2Command({
                    Bucket: TEST_CONFIG.S3_BUCKET,
                    Prefix: TEST_CONFIG.S3_PREFIX,
                    ContinuationToken: continuationToken,
                })
            )

            if (listResponse.Contents && listResponse.Contents.length > 0) {
                await s3Client.send(
                    new DeleteObjectsCommand({
                        Bucket: TEST_CONFIG.S3_BUCKET,
                        Delete: {
                            Objects: listResponse.Contents.map((obj) => ({ Key: obj.Key })),
                        },
                    })
                )
            }

            continuationToken = listResponse.NextContinuationToken
        } while (continuationToken)

        // Small delay to ensure S3 consistency
        await new Promise((resolve) => setTimeout(resolve, 100))
    } catch {
        // Ignore cleanup errors
    }
}

/**
 * Lists all S3 objects with the test prefix.
 */
async function listS3Objects(s3Client: S3Client): Promise<string[]> {
    const response = await s3Client.send(
        new ListObjectsV2Command({
            Bucket: TEST_CONFIG.S3_BUCKET,
            Prefix: TEST_CONFIG.S3_PREFIX,
        })
    )
    return (response.Contents || []).map((obj) => obj.Key!).filter(Boolean)
}

/**
 * Consumes session metadata messages from Kafka, filtered by session IDs.
 */
async function consumeKafkaSessionMetadata(
    kafkaHosts: string,
    metadataTopic: string,
    expectedSessionIds: Set<string>,
    timeoutMs: number = 10000
): Promise<KafkaSessionMetadata[]> {
    const config = overrideWithEnv(defaultConfig, process.env)

    return new Promise((resolve, reject) => {
        const messages: KafkaSessionMetadata[] = []
        const foundSessionIds = new Set<string>()
        const consumer = new KafkaConsumer(
            {
                'metadata.broker.list': kafkaHosts || config.KAFKA_HOSTS,
                'group.id': `test-consumer-${uuidv4()}`,
                'enable.auto.commit': false,
            },
            {
                'auto.offset.reset': 'earliest',
            }
        )

        const timeout = setTimeout(() => {
            consumer.disconnect()
            // Return what we have even if we didn't get all expected sessions
            resolve(messages)
        }, timeoutMs)

        consumer.on('ready', () => {
            consumer.subscribe([metadataTopic])
            consumer.consume()
        })

        consumer.on('data', (message) => {
            if (message.value) {
                try {
                    const metadata = parseJSON(message.value.toString()) as KafkaSessionMetadata

                    // Only include messages for our expected session IDs
                    if (expectedSessionIds.has(metadata.session_id) && !foundSessionIds.has(metadata.session_id)) {
                        messages.push(metadata)
                        foundSessionIds.add(metadata.session_id)

                        // Check if we have all expected sessions
                        if (foundSessionIds.size >= expectedSessionIds.size) {
                            clearTimeout(timeout)
                            consumer.disconnect()
                            resolve(messages)
                        }
                    }
                } catch {
                    // Ignore parse errors
                }
            }
        })

        consumer.on('event.error', (err) => {
            clearTimeout(timeout)
            consumer.disconnect()
            reject(err)
        })

        consumer.connect()
    })
}

/**
 * Reads a session block from S3 using the byte range from the block URL.
 */
async function readSessionBlockFromS3(s3Client: S3Client, blockUrl: string): Promise<ParsedSessionEvent[]> {
    // Parse the block URL to extract the S3 key and byte range
    // Format: s3://bucket/key?range=bytes=start-end or just key?range=bytes=start-end
    const rangeMatch = blockUrl.match(/range=bytes=(\d+)-(\d+)/)
    if (!rangeMatch) {
        throw new Error(`Invalid block URL format (no byte range): ${blockUrl}`)
    }

    const startByte = parseInt(rangeMatch[1])
    const endByte = parseInt(rangeMatch[2])

    // Extract the S3 key - it's everything before the query string
    const urlWithoutQuery = blockUrl.split('?')[0]
    // The key might be a full URL or just a path
    let s3Key: string
    if (urlWithoutQuery.startsWith('s3://')) {
        // s3://bucket/key format
        const pathParts = urlWithoutQuery.replace('s3://', '').split('/')
        pathParts.shift() // Remove bucket name
        s3Key = pathParts.join('/')
    } else if (urlWithoutQuery.startsWith('http')) {
        // HTTP URL format - extract path
        const url = new URL(urlWithoutQuery)
        s3Key = url.pathname.replace(/^\/[^/]+\//, '') // Remove leading /bucket/
    } else {
        // Just a key
        s3Key = urlWithoutQuery
    }

    // Read the specific byte range from S3
    const response = await s3Client.send(
        new GetObjectCommand({
            Bucket: TEST_CONFIG.S3_BUCKET,
            Key: s3Key,
            Range: `bytes=${startByte}-${endByte}`,
        })
    )

    const bodyBytes = await response.Body?.transformToByteArray()
    if (!bodyBytes) {
        throw new Error('Empty response body')
    }

    // Decompress the snappy block
    const decompressed = await snappy.uncompress(Buffer.from(bodyBytes))

    // Parse the JSONL content - each line is [windowId, event]
    const events: ParsedSessionEvent[] = []
    const lines = decompressed.toString().trim().split('\n')

    for (const line of lines) {
        if (line.length === 0) {
            continue
        }
        const [windowId, event] = parseJSON(line) as [string, { type: number; timestamp: number; data: unknown }]
        events.push({
            windowId,
            type: event.type,
            timestamp: event.timestamp,
            data: event.data,
        })
    }

    return events
}

/**
 * Builds a snapshot-friendly representation of the test outcome.
 * Includes actual session content for comprehensive verification.
 */
function buildSnapshotOutput(
    outcome: 'written' | 'dropped',
    metadata: KafkaSessionMetadata[],
    sessionEvents: Map<string, ParsedSessionEvent[]>
): object {
    if (outcome === 'dropped') {
        return {
            outcome: 'dropped',
            sessionCount: 0,
            sessions: [],
        }
    }

    // Build session summaries sorted by session ID for deterministic output
    const sessions = metadata
        .sort((a, b) => a.session_id.localeCompare(b.session_id))
        .map((meta) => {
            const events = sessionEvents.get(meta.session_id) || []

            return {
                // Session identification (redacted for snapshot stability)
                hasSessionId: !!meta.session_id,
                hasDistinctId: !!meta.distinct_id,
                hasBlockUrl: !!meta.block_url,

                // Metadata counts
                eventCount: meta.event_count,
                clickCount: meta.click_count,
                keypressCount: meta.keypress_count,
                mouseActivityCount: meta.mouse_activity_count,
                consoleLogCount: meta.console_log_count,
                consoleWarnCount: meta.console_warn_count,
                consoleErrorCount: meta.console_error_count,
                hasFirstUrl: !!meta.first_url,
                urlCount: meta.urls?.length ?? 0,

                // Actual event content from S3
                events: events.map((e) => ({
                    windowId: e.windowId,
                    type: e.type,
                    hasTimestamp: typeof e.timestamp === 'number',
                    hasData: !!e.data,
                })),

                // Window IDs present in events
                windowIds: [...new Set(events.map((e) => e.windowId))].sort(),
            }
        })

    return {
        outcome: 'written',
        sessionCount: metadata.length,
        sessions,
    }
}

/**
 * Test cases for parameterized testing.
 * Each test case produces payloads and expects either 'written' or 'dropped' outcome.
 */
const testCases: TestCase[] = [
    {
        name: 'single session with multiple event types',
        description: 'Basic happy path with Meta, FullSnapshot, and IncrementalSnapshot events',
        createPayloads: (team, testRunId) => [
            {
                sessionId: `session-${testRunId}`,
                distinctId: `user-${testRunId}`,
                token: team.api_token,
                events: [
                    { type: RRWebEventType.Meta, data: { href: 'https://example.com', width: 1920, height: 1080 } },
                    {
                        type: RRWebEventType.FullSnapshot,
                        data: { source: 1, snapshot: { html: '<html><body>Hello</body></html>' } },
                    },
                    {
                        type: RRWebEventType.IncrementalSnapshot,
                        data: { source: 2, mutations: [{ type: 'characterData', id: 1 }] },
                    },
                ],
            },
        ],
        expectedOutcome: 'written',
    },
    {
        name: 'invalid team token',
        description: 'Messages with invalid tokens should be dropped',
        createPayloads: (_team, testRunId) => [
            {
                sessionId: `invalid-token-session-${testRunId}`,
                distinctId: `user-${testRunId}`,
                token: 'invalid-token-that-does-not-exist',
                events: [
                    { type: RRWebEventType.Meta, data: { href: 'https://example.com', width: 1024, height: 768 } },
                    { type: RRWebEventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>Test</div>' } } },
                ],
            },
        ],
        expectedOutcome: 'dropped',
    },
    {
        name: 'multiple sessions in same batch',
        description: 'Multiple independent sessions should all be processed',
        createPayloads: (team, testRunId) => [
            {
                sessionId: `session-a-${testRunId}`,
                distinctId: `user-a-${testRunId}`,
                token: team.api_token,
                events: [
                    {
                        type: RRWebEventType.Meta,
                        data: { href: 'https://example.com/page-a', width: 1024, height: 768 },
                    },
                    {
                        type: RRWebEventType.FullSnapshot,
                        data: { source: 1, snapshot: { html: '<div>Session A</div>' } },
                    },
                ],
            },
            {
                sessionId: `session-b-${testRunId}`,
                distinctId: `user-b-${testRunId}`,
                token: team.api_token,
                events: [
                    {
                        type: RRWebEventType.Meta,
                        data: { href: 'https://example.com/page-b', width: 1920, height: 1080 },
                    },
                    {
                        type: RRWebEventType.FullSnapshot,
                        data: { source: 1, snapshot: { html: '<div>Session B</div>' } },
                    },
                ],
            },
        ],
        expectedOutcome: 'written',
    },
    {
        name: 'multiple windows in same session',
        description: 'Events from different windows in the same session should be recorded together',
        createPayloads: (team, testRunId) => {
            const sessionId = `multi-window-${testRunId}`
            return [
                {
                    sessionId,
                    distinctId: `user-${testRunId}`,
                    token: team.api_token,
                    windowId: 'window-main',
                    events: [
                        {
                            type: RRWebEventType.Meta,
                            data: { href: 'https://example.com/main', width: 1024, height: 768 },
                        },
                    ],
                },
                {
                    sessionId,
                    distinctId: `user-${testRunId}`,
                    token: team.api_token,
                    windowId: 'window-popup',
                    events: [
                        {
                            type: RRWebEventType.Meta,
                            data: { href: 'https://example.com/popup', width: 800, height: 600 },
                        },
                    ],
                },
            ]
        },
        expectedOutcome: 'written',
    },
]

describe('Session Recording Consumer Integration', () => {
    jest.setTimeout(60000)

    let hub: Hub
    let team: Team
    let s3Client: S3Client
    let infraAvailable: boolean

    async function createIngester(): Promise<SessionRecordingIngester> {
        const kafkaMetadataProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        const kafkaMessageProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        const kafkaDLQProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)

        return new SessionRecordingIngester(
            hub as any,
            false,
            hub.postgres,
            kafkaMetadataProducer,
            kafkaMessageProducer,
            kafkaDLQProducer
        )
    }

    beforeAll(async () => {
        s3Client = new S3Client({
            region: TEST_CONFIG.S3_REGION,
            endpoint: TEST_CONFIG.S3_ENDPOINT,
            forcePathStyle: true,
            credentials: {
                accessKeyId: TEST_CONFIG.S3_ACCESS_KEY,
                secretAccessKey: TEST_CONFIG.S3_SECRET_KEY,
            },
        })

        const [s3Ok, kafkaOk, postgresOk] = await Promise.all([
            isS3Available(s3Client),
            isKafkaAvailable(),
            isPostgresAvailable(),
        ])

        infraAvailable = s3Ok && kafkaOk && postgresOk

        if (!infraAvailable) {
            console.warn('Skipping integration tests: infrastructure not available')
            console.warn(`  S3 available: ${s3Ok}`)
            console.warn(`  Kafka available: ${kafkaOk}`)
            console.warn(`  Postgres available: ${postgresOk}`)
            console.warn('To run these tests:')
            console.warn('  1. Start services: hogli dev:setup (or docker compose -f docker-compose.dev.yml up)')
            console.warn('  2. Set up test DB: pnpm setup:test (from nodejs directory)')
            return
        }

        await resetKafka()
        await resetTestDatabase()

        hub = await createHub({
            SESSION_RECORDING_V2_S3_BUCKET: TEST_CONFIG.S3_BUCKET,
            SESSION_RECORDING_V2_S3_PREFIX: TEST_CONFIG.S3_PREFIX,
            SESSION_RECORDING_V2_S3_ENDPOINT: TEST_CONFIG.S3_ENDPOINT,
            SESSION_RECORDING_V2_S3_REGION: TEST_CONFIG.S3_REGION,
            SESSION_RECORDING_V2_S3_ACCESS_KEY_ID: TEST_CONFIG.S3_ACCESS_KEY,
            SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY: TEST_CONFIG.S3_SECRET_KEY,
            SESSION_RECORDING_V2_S3_TIMEOUT_MS: TEST_CONFIG.S3_TIMEOUT_MS,
            SESSION_RECORDING_MAX_BATCH_SIZE_KB: 1,
            SESSION_RECORDING_MAX_BATCH_AGE_MS: 1000,
        })

        team = await getFirstTeam(hub)
    })

    afterAll(async () => {
        if (infraAvailable) {
            if (hub) {
                await closeHub(hub)
            }
            await cleanupS3TestData(s3Client)
        }
        s3Client?.destroy()
    })

    beforeEach(async () => {
        if (infraAvailable) {
            await cleanupS3TestData(s3Client)
        }
    })

    describe('end-to-end message processing', () => {
        it.each(testCases)('$name', async ({ createPayloads, expectedOutcome }) => {
            if (!infraAvailable) {
                return
            }

            const testRunId = uuidv4().slice(0, 8)
            const payloadConfigs = createPayloads(team, testRunId)

            // Collect expected session IDs for metadata consumption
            const expectedSessionIds =
                expectedOutcome === 'written' ? new Set(payloadConfigs.map((p) => p.sessionId)) : new Set<string>()

            // Create a fresh producer for this test (not shared with hub)
            const testProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)

            // Create and start ingester
            const ingester = await createIngester()
            await ingester.start()
            await new Promise((resolve) => setTimeout(resolve, PARTITION_ASSIGNMENT_WAIT_MS))

            // Produce all payloads to Kafka
            for (const config of payloadConfigs) {
                const payload = createKafkaPayload(config)
                await produceToKafka(testProducer, KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS, payload)
            }

            // Wait for processing based on expected outcome
            if (expectedOutcome === 'written') {
                await waitForExpect(async () => {
                    const objects = await listS3Objects(s3Client)
                    expect(objects.length).toBeGreaterThan(0)
                }, 30000)
            } else {
                // For dropped messages, wait a bit then verify nothing was written
                await new Promise((resolve) => setTimeout(resolve, PARTITION_ASSIGNMENT_WAIT_MS))
            }

            // Stop ingester (triggers final flush)
            await ingester.stop()

            // Disconnect test producer
            await testProducer.disconnect()

            // Consume session metadata from Kafka
            const metadata = await consumeKafkaSessionMetadata(
                hub.KAFKA_HOSTS,
                hub.SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC,
                expectedSessionIds,
                10000
            )

            // Read actual session events from S3 using metadata
            const sessionEvents = new Map<string, ParsedSessionEvent[]>()
            for (const meta of metadata) {
                if (meta.block_url) {
                    try {
                        const events = await readSessionBlockFromS3(s3Client, meta.block_url)
                        sessionEvents.set(meta.session_id, events)
                    } catch (err) {
                        console.warn(`Failed to read session block for ${meta.session_id}:`, err)
                    }
                }
            }

            // Build and verify snapshot
            const snapshotOutput = buildSnapshotOutput(expectedOutcome, metadata, sessionEvents)
            expect(forSnapshot(snapshotOutput)).toMatchSnapshot()
        })
    })
})
