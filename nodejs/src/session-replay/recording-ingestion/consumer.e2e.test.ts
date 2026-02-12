/**
 * E2E test for the session recording consumer.
 *
 * Validates the full session recording pipeline using real local infrastructure.
 * See README.md for architecture details, setup instructions, and how to add new test cases.
 */
import { DeleteObjectsCommand, GetObjectCommand, ListObjectsV2Command, S3Client } from '@aws-sdk/client-s3'
import { HighLevelProducer } from 'node-rdkafka'
import snappy from 'snappy'
import { v4 as uuidv4 } from 'uuid'

import { Clickhouse } from '../../../tests/helpers/clickhouse'
import { waitForExpect } from '../../../tests/helpers/expectations'
import { resetKafka } from '../../../tests/helpers/kafka'
import { forSnapshot } from '../../../tests/helpers/snapshots'
import { createOrganization, createTeam, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { defaultConfig, overrideWithEnv } from '../../config/config'
import {
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
} from '../../config/kafka-topics'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { REDIS_KEY_PREFIX, RedisRestrictionType } from '../../utils/event-ingestion-restrictions/redis-schema'
import { parseJSON } from '../../utils/json-parse'
import { SessionRecordingIngester } from './consumer'
import { MouseInteractions, RRWebEventSource, RRWebEventType } from './rrweb-types'

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

// Token for a team that has DROP_EVENT restriction applied
// This team is created in beforeAll and the restriction is set in Redis
const RESTRICTED_TEAM_TOKEN = 'restricted-team-token-for-e2e-tests'

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
 * Aggregated session metadata from ClickHouse.
 *
 * This represents session data after it has been processed by the materialized view
 * and aggregated in the session_replay_events table. A session may have multiple
 * block_urls if it was flushed multiple times during recording.
 */
interface SessionMetadata {
    session_id: string
    team_id: number
    distinct_id: string
    block_urls: string[]
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
 * Checks if ClickHouse is available with the Kafka engine table.
 */
async function isClickHouseAvailable(clickhouse: Clickhouse): Promise<boolean> {
    try {
        await clickhouse.query('SELECT 1')
        return true
    } catch {
        return false
    }
}

/**
 * Cleans up test data from S3, handling pagination for large result sets.
 */
async function cleanupS3TestData(s3Client: S3Client): Promise<void> {
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
 * Raw result from the aggregated session_replay_events table.
 * The schema uses aggregate functions that need special handling.
 */
interface ClickHouseSessionReplayRow {
    session_id: string
    team_id: number
    distinct_id: string
    block_urls: string[]
    event_count: number
    first_url: string | null
    all_urls: string[]
    click_count: number
    keypress_count: number
    mouse_activity_count: number
    console_log_count: number
    console_warn_count: number
    console_error_count: number
    size: number
}

/**
 * Queries session metadata from the ClickHouse aggregated table.
 *
 * The materialized view (`session_replay_events_mv`) continuously processes data from
 * the Kafka engine table and writes aggregated results to `session_replay_events`.
 * We query this table with FINAL to get properly merged results.
 */
async function queryClickHouseSessionMetadata(
    clickhouse: Clickhouse,
    expectedSessionIds: Set<string>,
    timeoutMs: number = 10000
): Promise<SessionMetadata[]> {
    if (expectedSessionIds.size === 0) {
        return []
    }

    const sessionIdsList = Array.from(expectedSessionIds)
        .map((id) => `'${id}'`)
        .join(', ')

    // Poll the aggregated table until we find all expected sessions or timeout
    const startTime = Date.now()
    const foundMetadata = new Map<string, SessionMetadata>()

    while (Date.now() - startTime < timeoutMs) {
        // Query the aggregated table with FINAL to get merged results
        // block_urls is an array containing all S3 block URLs for this session
        const results = await clickhouse.query<ClickHouseSessionReplayRow>(`
            SELECT
                session_id,
                team_id,
                distinct_id,
                block_urls,
                event_count,
                argMinMerge(first_url) as first_url,
                all_urls,
                click_count,
                keypress_count,
                mouse_activity_count,
                console_log_count,
                console_warn_count,
                console_error_count,
                size
            FROM session_replay_events
            FINAL
            WHERE session_id IN (${sessionIdsList})
            GROUP BY session_id, team_id, distinct_id, block_urls, event_count, all_urls,
                     click_count, keypress_count, mouse_activity_count,
                     console_log_count, console_warn_count, console_error_count, size
        `)

        // Transform to SessionMetadata format and collect results
        for (const row of results) {
            if (!foundMetadata.has(row.session_id)) {
                // Filter out empty block URLs from the array
                const blockUrls = (row.block_urls ?? []).filter((url) => url && url.length > 0)
                foundMetadata.set(row.session_id, {
                    session_id: row.session_id,
                    team_id: row.team_id,
                    distinct_id: row.distinct_id,
                    block_urls: blockUrls,
                    event_count: row.event_count,
                    first_url: row.first_url,
                    urls: row.all_urls ?? [],
                    click_count: row.click_count,
                    keypress_count: row.keypress_count,
                    mouse_activity_count: row.mouse_activity_count,
                    console_log_count: row.console_log_count,
                    console_warn_count: row.console_warn_count,
                    console_error_count: row.console_error_count,
                    size: row.size,
                })
            }
        }

        // Check if we have all expected sessions
        if (foundMetadata.size >= expectedSessionIds.size) {
            break
        }

        // Small delay before next poll
        await new Promise((resolve) => setTimeout(resolve, 100))
    }

    return Array.from(foundMetadata.values())
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
    metadata: SessionMetadata[],
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
                blockUrlCount: meta.block_urls.length,

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

                // Actual event content from S3 (from all blocks)
                events: events.map((e) => ({
                    windowId: e.windowId,
                    type: e.type,
                    hasTimestamp: typeof e.timestamp === 'number',
                    hasData: !!e.data,
                })),

                // Window IDs present in events
                windowIds: Array.from(new Set(events.map((e) => e.windowId))).sort(),
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
    {
        name: 'session continuity across batches',
        description: 'Events arriving in separate batches for the same session should be combined',
        createPayloads: (team, testRunId) => {
            const sessionId = `continuous-session-${testRunId}`
            const baseTimestamp = Date.now()
            return [
                {
                    sessionId,
                    distinctId: `user-${testRunId}`,
                    token: team.api_token,
                    events: [
                        {
                            type: RRWebEventType.Meta,
                            data: { href: 'https://example.com/page1', width: 1024, height: 768 },
                            timestamp: baseTimestamp,
                        },
                        {
                            type: RRWebEventType.FullSnapshot,
                            data: { source: 1, snapshot: { html: '<div>First batch</div>' } },
                            timestamp: baseTimestamp + 1000,
                        },
                    ],
                },
                {
                    sessionId,
                    distinctId: `user-${testRunId}`,
                    token: team.api_token,
                    events: [
                        {
                            type: RRWebEventType.IncrementalSnapshot,
                            data: { source: 2, mutations: [{ type: 'characterData', id: 1 }] },
                            timestamp: baseTimestamp + 2000,
                        },
                        {
                            type: RRWebEventType.IncrementalSnapshot,
                            data: { source: 2, mutations: [{ type: 'characterData', id: 2 }] },
                            timestamp: baseTimestamp + 3000,
                        },
                    ],
                },
            ]
        },
        expectedOutcome: 'written',
    },
    {
        name: 'out of order events',
        description: 'Events with timestamps out of chronological order should still be processed',
        createPayloads: (team, testRunId) => {
            const baseTimestamp = Date.now()
            return [
                {
                    sessionId: `out-of-order-${testRunId}`,
                    distinctId: `user-${testRunId}`,
                    token: team.api_token,
                    events: [
                        {
                            type: RRWebEventType.Meta,
                            data: { href: 'https://example.com', width: 1024, height: 768 },
                            timestamp: baseTimestamp + 2000, // Second event sent first
                        },
                        {
                            type: RRWebEventType.FullSnapshot,
                            data: { source: 1, snapshot: { html: '<div>First</div>' } },
                            timestamp: baseTimestamp, // First event sent second
                        },
                        {
                            type: RRWebEventType.IncrementalSnapshot,
                            data: { source: 2, mutations: [] },
                            timestamp: baseTimestamp + 1000, // Middle event sent last
                        },
                    ],
                },
            ]
        },
        expectedOutcome: 'written',
    },
    {
        name: 'empty events array',
        description: 'Messages with no events should be handled gracefully',
        createPayloads: (team, testRunId) => [
            {
                sessionId: `empty-events-${testRunId}`,
                distinctId: `user-${testRunId}`,
                token: team.api_token,
                events: [],
            },
        ],
        expectedOutcome: 'dropped',
    },
    {
        name: 'console log events',
        description: 'Console log, warn, and error events should be counted in metadata',
        createPayloads: (team, testRunId) => [
            {
                sessionId: `console-logs-${testRunId}`,
                distinctId: `user-${testRunId}`,
                token: team.api_token,
                events: [
                    { type: RRWebEventType.Meta, data: { href: 'https://example.com', width: 1024, height: 768 } },
                    {
                        type: RRWebEventType.Plugin,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'log', payload: ['Hello world'] } },
                    },
                    {
                        type: RRWebEventType.Plugin,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'info', payload: ['Info message'] } },
                    },
                    {
                        type: RRWebEventType.Plugin,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'warn', payload: ['Warning!'] } },
                    },
                    {
                        type: RRWebEventType.Plugin,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'error', payload: ['Error occurred'] } },
                    },
                    {
                        type: RRWebEventType.Plugin,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'error', payload: ['Another error'] } },
                    },
                ],
            },
        ],
        expectedOutcome: 'written',
    },
    {
        name: 'click and keypress events',
        description: 'Click and keypress events should be counted in metadata',
        createPayloads: (team, testRunId) => [
            {
                sessionId: `clicks-keypresses-${testRunId}`,
                distinctId: `user-${testRunId}`,
                token: team.api_token,
                events: [
                    { type: RRWebEventType.Meta, data: { href: 'https://example.com', width: 1024, height: 768 } },
                    // Click events
                    {
                        type: RRWebEventType.IncrementalSnapshot,
                        data: { source: RRWebEventSource.MouseInteraction, type: MouseInteractions.Click, id: 1 },
                    },
                    {
                        type: RRWebEventType.IncrementalSnapshot,
                        data: { source: RRWebEventSource.MouseInteraction, type: MouseInteractions.DblClick, id: 2 },
                    },
                    {
                        type: RRWebEventType.IncrementalSnapshot,
                        data: { source: RRWebEventSource.MouseInteraction, type: MouseInteractions.Click, id: 3 },
                    },
                    // Keypress events (Input source)
                    {
                        type: RRWebEventType.IncrementalSnapshot,
                        data: { source: RRWebEventSource.Input, id: 10, text: 'hello' },
                    },
                    {
                        type: RRWebEventType.IncrementalSnapshot,
                        data: { source: RRWebEventSource.Input, id: 11, text: 'world' },
                    },
                ],
            },
        ],
        expectedOutcome: 'written',
    },
    {
        name: 'token with DROP_EVENT restriction',
        description: 'Messages from a token with DROP_EVENT restriction should be dropped',
        createPayloads: (_team, testRunId) => [
            {
                sessionId: `restricted-session-${testRunId}`,
                distinctId: `user-${testRunId}`,
                token: RESTRICTED_TEAM_TOKEN,
                events: [
                    { type: RRWebEventType.Meta, data: { href: 'https://example.com', width: 1024, height: 768 } },
                    { type: RRWebEventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>Test</div>' } } },
                ],
            },
        ],
        expectedOutcome: 'dropped',
    },
]

describe('Session Recording Consumer Integration', () => {
    jest.setTimeout(60000)

    let hub: Hub
    let team: Team
    let s3Client: S3Client
    let clickhouse: Clickhouse

    interface IngesterWithProducers {
        ingester: SessionRecordingIngester
        kafkaMetadataProducer: KafkaProducerWrapper
    }

    async function createIngester(): Promise<IngesterWithProducers> {
        const kafkaMetadataProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        const kafkaMessageProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        const kafkaDLQProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)

        const ingester = new SessionRecordingIngester(
            hub as any,
            false,
            hub.postgres,
            kafkaMetadataProducer,
            kafkaMessageProducer,
            kafkaDLQProducer
        )

        return { ingester, kafkaMetadataProducer }
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

        clickhouse = Clickhouse.create()

        // Verify all required infrastructure is available
        // Tests will fail (not skip) if infrastructure is missing
        const [s3Ok, kafkaOk, postgresOk, clickhouseOk] = await Promise.all([
            isS3Available(s3Client),
            isKafkaAvailable(),
            isPostgresAvailable(),
            isClickHouseAvailable(clickhouse),
        ])

        const missing: string[] = []
        if (!s3Ok) {
            missing.push('S3/MinIO')
        }
        if (!kafkaOk) {
            missing.push('Kafka')
        }
        if (!postgresOk) {
            missing.push('Postgres')
        }
        if (!clickhouseOk) {
            missing.push('ClickHouse')
        }

        if (missing.length > 0) {
            throw new Error(
                `Required infrastructure not available: ${missing.join(', ')}.\n` +
                    'To run these tests:\n' +
                    '  1. Start services: hogli dev:setup (or docker compose -f docker-compose.dev.yml up)\n' +
                    '  2. Set up test DB: pnpm setup:test (from nodejs directory)\n' +
                    'To skip these tests, use: pnpm jest --testPathIgnorePatterns=e2e'
            )
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
            // Use the test topic (with _test suffix) to match ClickHouse's Kafka engine table
            SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
        })

        team = await getFirstTeam(hub)

        // Enable console log capture for the primary team so console log tests work
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            'UPDATE posthog_team SET capture_console_log_opt_in = true WHERE id = $1',
            [team.id],
            'enable-console-log-capture'
        )

        // Create a second team with a known token that will have DROP_EVENT restriction
        const restrictedOrgId = await createOrganization(hub.postgres)
        await createTeam(hub.postgres, restrictedOrgId, RESTRICTED_TEAM_TOKEN)

        // Set up DROP_EVENT restriction in Redis for the restricted team
        // The ingester's restriction manager will read this when it starts
        const redisClient = await hub.redisPool.acquire()
        try {
            const key = `${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`
            const restriction = [
                {
                    version: 2,
                    token: RESTRICTED_TEAM_TOKEN,
                    pipelines: ['session_recordings'],
                },
            ]
            await redisClient.set(key, JSON.stringify(restriction))
        } finally {
            await hub.redisPool.release(redisClient)
        }
    })

    afterAll(async () => {
        // Clean up the DROP_EVENT restriction from Redis
        if (hub?.redisPool) {
            const redisClient = await hub.redisPool.acquire()
            try {
                const key = `${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`
                await redisClient.del(key)
            } finally {
                await hub.redisPool.release(redisClient)
            }
        }

        if (hub) {
            await closeHub(hub)
        }
        await cleanupS3TestData(s3Client)
        s3Client?.destroy()
        clickhouse?.close()
    })

    beforeEach(async () => {
        await cleanupS3TestData(s3Client)
    })

    describe('end-to-end message processing', () => {
        it.each(testCases)('$name', async ({ createPayloads, expectedOutcome }) => {
            const testRunId = uuidv4().slice(0, 8)
            const payloadConfigs = createPayloads(team, testRunId)

            // Collect expected session IDs for metadata consumption
            const expectedSessionIds =
                expectedOutcome === 'written' ? new Set(payloadConfigs.map((p) => p.sessionId)) : new Set<string>()

            // Create a fresh producer for this test (not shared with hub)
            const testProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)

            // Create and start ingester
            const { ingester, kafkaMetadataProducer } = await createIngester()
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

            // Disconnect producers created for this test
            await kafkaMetadataProducer.disconnect()
            await testProducer.disconnect()

            // Query session metadata from ClickHouse aggregated table
            // The MV processes Kafka messages asynchronously, so we poll until data appears
            const metadata = await queryClickHouseSessionMetadata(clickhouse, expectedSessionIds, 30000)

            // Read actual session events from S3 using metadata
            // A session may have multiple blocks if it was flushed multiple times
            const sessionEvents = new Map<string, ParsedSessionEvent[]>()
            for (const meta of metadata) {
                const allEvents: ParsedSessionEvent[] = []
                for (const blockUrl of meta.block_urls) {
                    try {
                        const events = await readSessionBlockFromS3(s3Client, blockUrl)
                        allEvents.push(...events)
                    } catch (err) {
                        console.warn(`Failed to read session block for ${meta.session_id}:`, err)
                    }
                }
                if (allEvents.length > 0) {
                    sessionEvents.set(meta.session_id, allEvents)
                }
            }

            // Build and verify snapshot
            const snapshotOutput = buildSnapshotOutput(expectedOutcome, metadata, sessionEvents)
            expect(forSnapshot(snapshotOutput)).toMatchSnapshot()
        })
    })
})
