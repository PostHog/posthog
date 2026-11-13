import type { MetricsParityError, MetricsParityScenario, ParityHeader, ParityMessage } from './parity-types'

// Mid-hour, so the app metric timestamp and the token bucket refill both show.
const PARITY_NOW_MS = Date.UTC(2025, 0, 15, 12, 37, 13, 250)
const INPUT_TOPIC = 'metrics_ingestion_test'

const LIMITER_OFF = {
    METRICS_LIMITER_ENABLED_TEAMS: '',
    METRICS_LIMITER_DISABLED_FOR_TEAMS: '',
    METRICS_LIMITER_BUCKET_SIZE_KB: 10000,
    METRICS_LIMITER_REFILL_RATE_KB_PER_SECOND: 1000,
    METRICS_LIMITER_TTL_SECONDS: 86400,
    METRICS_LIMITER_TEAM_BUCKET_SIZE_KB: '',
    METRICS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '',
    METRICS_LIMITER_FAIL_OPEN: false,
    // Rust has no aggregation step, and its replay refuses a scenario that enables one.
    // Port the step before a scenario sets this.
    METRICS_AGGREGATION_ENABLED_TEAMS: '',
}

function iso(offsetMs: number): string {
    return new Date(PARITY_NOW_MS + offsetMs).toISOString()
}

let valueCounter = 0

/** Every value differs, so an output maps back to one input. */
function packet(label: string): string {
    valueCounter++
    return Buffer.from(`opaque otlp metrics packet ${valueCounter} ${label}`).toString('base64')
}

type MessageOptions = {
    partition?: number
    offset: number
    key?: string | null
    value?: string | null
    timestampOffsetMs?: number
}

function message(headers: ParityHeader[], options: MessageOptions): ParityMessage {
    return {
        topic: INPUT_TOPIC,
        partition: options.partition ?? 0,
        offset: options.offset,
        timestamp: PARITY_NOW_MS + (options.timestampOffsetMs ?? -2_000),
        key: options.key ?? null,
        headers,
        value_b64: options.value === undefined ? packet(`${options.partition ?? 0}:${options.offset}`) : options.value,
    }
}

/** The headers capture writes for one OTLP request. */
function sized(token: string, bytes: number, records: number, extra: ParityHeader[] = []): ParityHeader[] {
    return [
        ['token', token],
        ['bytes_uncompressed', String(bytes)],
        ['bytes_uncompressed_records', String(bytes * 2)],
        ['bytes_compressed', String(Math.ceil(bytes / 3))],
        ['record_count', String(records)],
        ...extra,
    ]
}

function error(kind: MetricsParityError['kind'], text: string): MetricsParityError {
    return { kind, message: text }
}

function base(name: string, description: string): MetricsParityScenario {
    return {
        name,
        description,
        batch_now_ms: [],
        config: { ...LIMITER_OFF },
        teams: [],
        quota_limited_tokens: [],
        team_lookup_faults: {},
        produce_faults: [],
        batches: [],
    }
}

function passthrough(): MetricsParityScenario {
    return {
        ...base(
            'passthrough',
            'Packets pass unchanged, with the ClickHouse headers added and the usage billed per team.'
        ),
        teams: [
            { id: 201, api_token: 'token-alpha' },
            { id: 202, api_token: 'token-beta' },
        ],
        batch_now_ms: [PARITY_NOW_MS, PARITY_NOW_MS + 1_000, PARITY_NOW_MS + 2_000],
        batches: [
            [
                message(
                    sized('token-alpha', 1200, 4, [
                        ['created_at', iso(-1_500)],
                        ['content-encoding', 'zstd'],
                    ]),
                    {
                        offset: 10,
                    }
                ),
                message([['token', 'token-beta']], { offset: 11, key: 'routing-key' }),
                message(
                    [
                        ['record_count', '1'],
                        ['token', 'token-alpha'],
                        ['bytes_uncompressed', '500'],
                        ['record_count', '3'],
                    ],
                    { offset: 12, partition: 3, timestampOffsetMs: -86_400_000 }
                ),
                message(sized('token-beta', 64, 1), {
                    offset: 13,
                    value: Buffer.from([0, 1, 2, 250, 251, 252, 253, 254, 255]).toString('base64'),
                }),
                message(sized('token-alpha', 0, 0), { offset: 14 }),
            ],
            [],
            [
                message(sized('token-beta', 9000, 30), { offset: 0, partition: 1 }),
                message(sized('token-beta', 3000, 10), { offset: 0, partition: 2 }),
            ],
        ],
    }
}

function drops(): MetricsParityScenario {
    return {
        ...base('drops', 'Header, team, quota and null-value drops, and which of them still bill.'),
        teams: [
            { id: 211, api_token: 'token-gamma' },
            { id: 212, api_token: 'token-quota' },
        ],
        quota_limited_tokens: ['token-quota'],
        batch_now_ms: [PARITY_NOW_MS],
        batches: [
            [
                message([['bytes_uncompressed', '10']], { offset: 0 }),
                message([['token', '']], { offset: 1 }),
                message(sized('token-gamma', 10, 1, [['bytes_uncompressed', '-1']]), { offset: 2 }),
                message(sized('token-gamma', 10, 1, [['record_count', '1.5']]), { offset: 3 }),
                message(sized('token-gamma', 10, 1, [['bytes_compressed', ' 12']]), { offset: 4 }),
                message(sized('token-gamma', 10, 1, [['bytes_uncompressed_records', '']]), { offset: 5 }),
                message(sized('token-gamma', 10, 1, [['bytes_uncompressed', '9007199254740992']]), { offset: 6 }),
                message(sized('token-gamma', 10, 1, [['bytes_uncompressed', '٣']]), { offset: 7 }),
                message(sized('token-gamma', 10, 1, [['bytes_uncompressed', '0007']]), { offset: 8 }),
                message(sized('token-gamma', 10, 1, [['bytes_uncompressed', '9007199254740991']]), { offset: 9 }),
                message(sized('token-unknown', 10, 1), { offset: 10 }),
                message(sized('token-quota', 700, 7), { offset: 11 }),
                message(sized('token-gamma', 300, 3), { offset: 12, value: null }),
                message(sized('token-gamma', 100, 2), { offset: 13 }),
            ],
        ],
    }
}

function rateLimit(): MetricsParityScenario {
    return {
        ...base(
            'rate-limit',
            'Per-team token buckets in Redis: partial batches, team overrides, disabled teams, refill.'
        ),
        config: {
            ...LIMITER_OFF,
            METRICS_LIMITER_ENABLED_TEAMS: '*',
            METRICS_LIMITER_DISABLED_FOR_TEAMS: ' 303, x',
            METRICS_LIMITER_BUCKET_SIZE_KB: 10,
            METRICS_LIMITER_REFILL_RATE_KB_PER_SECOND: 1,
            METRICS_LIMITER_TEAM_BUCKET_SIZE_KB: '302:3,bad,302 : 4',
            METRICS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '302:2',
        },
        teams: [
            { id: 301, api_token: 'token-limited-a' },
            { id: 302, api_token: 'token-limited-b' },
            { id: 303, api_token: 'token-unlimited' },
        ],
        batch_now_ms: [PARITY_NOW_MS, PARITY_NOW_MS + 3_000, PARITY_NOW_MS + 60_000],
        batches: [
            [
                message(sized('token-limited-a', 4000, 4, [['created_at', iso(-5_000)]]), { offset: 0 }),
                message(sized('token-limited-a', 4000, 4, [['created_at', iso(-4_000)]]), { offset: 1 }),
                message(sized('token-limited-a', 4000, 4, [['created_at', 'not a date']]), { offset: 2 }),
                message(sized('token-limited-a', 1, 1), { offset: 3 }),
                message(sized('token-limited-b', 1500, 2, [['created_at', iso(-1_000)]]), { offset: 4 }),
                message(sized('token-limited-b', 1001, 2, [['created_at', iso(-1_000)]]), { offset: 5 }),
                message(sized('token-limited-b', 1, 1, [['created_at', iso(-1_000)]]), { offset: 6 }),
                message(sized('token-unlimited', 900_000, 90), { offset: 7 }),
            ],
            [
                message(sized('token-limited-a', 2500, 2, [['created_at', iso(2_000)]]), { offset: 8 }),
                message(sized('token-limited-a', 2500, 2, [['created_at', iso(2_500)]]), { offset: 9 }),
                message(sized('token-limited-b', 3000, 3, [['created_at', iso(2_500)]]), { offset: 10 }),
            ],
            [
                message(sized('token-limited-a', 9999, 9, [['created_at', iso(59_000)]]), { offset: 11 }),
                message(sized('token-limited-b', 4000, 4, [['created_at', iso(59_000)]]), { offset: 12 }),
            ],
        ],
    }
}

function produceFaults(): MetricsParityScenario {
    return {
        ...base('produce-faults', 'Produce retries, DLQ routing with the team headers, and a lost usage write.'),
        teams: [
            { id: 401, api_token: 'token-too-large' },
            { id: 402, api_token: 'token-flaky' },
            { id: 403, api_token: 'token-broker-down' },
            { id: 404, api_token: 'token-rejected' },
            { id: 405, api_token: 'token-healthy' },
        ],
        produce_faults: [
            { output: 'metrics', team_id: '401', times: 1, error: error('message_size_too_large', 'too large') },
            { output: 'metrics', team_id: '402', times: 2, error: error('error', 'local: message timed out') },
            {
                output: 'metrics',
                team_id: '403',
                times: 5,
                error: error('dependency_unavailable', 'broker transport failure'),
            },
            { output: 'metrics', team_id: '404', times: 1, error: error('non_retriable', 'invalid record') },
            { output: 'app_metrics', times: 1, error: error('error', 'app metrics broker down') },
        ],
        batch_now_ms: [PARITY_NOW_MS, PARITY_NOW_MS + 5_000],
        batches: [
            [
                message(sized('token-too-large', 50_000, 500, [['created_at', iso(-1)]]), { offset: 0 }),
                message(sized('token-flaky', 200, 2), { offset: 1 }),
                message(sized('token-broker-down', 300, 3), { offset: 2 }),
                message(sized('token-rejected', 400, 4), { offset: 3 }),
                message(sized('token-healthy', 500, 5), { offset: 4 }),
            ],
            [message(sized('token-healthy', 600, 6), { offset: 5 })],
        ],
    }
}

function teamLookup(): MetricsParityScenario {
    return {
        ...base(
            'team-lookup',
            'A failed lookup goes to the DLQ, a retriable one is retried, and one that stays down fails the batch.'
        ),
        teams: [
            { id: 501, api_token: 'token-lookup-bad' },
            { id: 502, api_token: 'token-lookup-flaky' },
            { id: 503, api_token: 'token-lookup-down' },
            { id: 504, api_token: 'token-lookup-ok' },
        ],
        team_lookup_faults: {
            'token-lookup-bad': { ...error('error', 'bad token row'), times: 1 },
            'token-lookup-flaky': { ...error('dependency_unavailable', 'pg restarting'), times: 2 },
            'token-lookup-down': { ...error('dependency_unavailable', 'pg down'), times: 3 },
        },
        batch_now_ms: [PARITY_NOW_MS, PARITY_NOW_MS + 1_000],
        batches: [
            [
                message(sized('token-lookup-bad', 100, 1), { offset: 0 }),
                message(sized('token-lookup-flaky', 200, 2), { offset: 1 }),
                message(sized('token-lookup-ok', 300, 3), { offset: 2 }),
            ],
            // Last, because Node does not reuse a pipeline after it throws.
            [message(sized('token-lookup-down', 400, 4), { offset: 3 })],
        ],
    }
}

function dlqDown(name: string, description: string, fault: 'produce' | 'lookup'): MetricsParityScenario {
    const scenario: MetricsParityScenario = {
        ...base(name, description),
        teams: [
            { id: 601, api_token: 'token-dlq-a' },
            { id: 602, api_token: 'token-dlq-b' },
        ],
        produce_faults: [{ output: 'dlq', times: 1, error: error('error', 'dlq broker down') }],
        batch_now_ms: [PARITY_NOW_MS, PARITY_NOW_MS + 1_000],
        batches: [
            [message(sized('token-dlq-b', 100, 1), { offset: 0 })],
            // Last, because a failed side effect stays latched in Node's scheduler.
            [
                message(sized('token-dlq-a', 200, 2), { offset: 1 }),
                message(sized('token-dlq-b', 300, 3), { offset: 2 }),
            ],
        ],
    }
    if (fault === 'produce') {
        scenario.produce_faults.unshift({
            output: 'metrics',
            team_id: '601',
            times: 1,
            error: error('message_size_too_large', 'too large'),
        })
    } else {
        scenario.team_lookup_faults['token-dlq-a'] = { ...error('error', 'bad token row'), times: 1 }
    }
    return scenario
}

export function buildMetricsParityScenarios(): MetricsParityScenario[] {
    valueCounter = 0
    return [
        passthrough(),
        drops(),
        rateLimit(),
        produceFaults(),
        teamLookup(),
        dlqDown(
            'dlq-down-produce',
            'A produce that fails and whose DLQ write fails rejects the background task.',
            'produce'
        ),
        dlqDown('dlq-down-lookup', 'A lookup DLQ write that fails rejects the background task.', 'lookup'),
    ]
}
