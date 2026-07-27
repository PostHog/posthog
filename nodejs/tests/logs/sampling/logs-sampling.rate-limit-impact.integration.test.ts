import avro from 'avsc'

import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { type LogRecord, decodeLogRecords, encodeLogRecords } from '~/logs/log-record-avro'
import { compileRuleSet } from '~/logs/sampling/compile-rules'
import { LogsSamplingService } from '~/logs/sampling/logs-sampling.service'
import { Hub } from '~/types'

// Real-Redis integration test: drives the genuine token-bucket Lua with a mocked clock so we can
// simulate a sustained log stream at different volumes deterministically (no sleeps). This is the
// "save → impact" half of the rate-limit contract: it feeds the limiter the EXACT config shape the
// drop-rule form writes (`kb_per_second` / `burst_kb`) and asserts the drop impact. The producer
// side (form → that shape) is locked in by
// products/logs/frontend/components/LogsSampling/logsSamplingFormLogic.test.ts.

const LOG_RECORD_AVRO = avro.Type.forSchema({
    type: 'record',
    name: 'LogRecord',
    fields: [
        { name: 'uuid', type: ['null', 'string'] },
        { name: 'trace_id', type: ['null', 'bytes'] },
        { name: 'span_id', type: ['null', 'bytes'] },
        { name: 'trace_flags', type: ['null', 'int'] },
        { name: 'timestamp', type: ['null', 'long'] },
        { name: 'observed_timestamp', type: ['null', 'long'] },
        { name: 'body', type: ['null', 'string'] },
        { name: 'severity_text', type: ['null', 'string'] },
        { name: 'severity_number', type: ['null', 'int'] },
        { name: 'service_name', type: ['null', 'string'] },
        { name: 'resource_attributes', type: ['null', { type: 'map', values: 'string' }] },
        { name: 'instrumentation_scope', type: ['null', 'string'] },
        { name: 'event_name', type: ['null', 'string'] },
        { name: 'attributes', type: ['null', { type: 'map', values: 'string' }] },
        { name: 'bytes_uncompressed', type: ['null', 'long'] },
    ],
})

const logsSettings = { json_parse_logs: false, pii_scrub_logs: false }
const SERVICE = 'smokescreen'
const TEAM_ID = 4242
// LogsSamplingService names its limiter 'logs-sampling-rate'; key prefix uses the test root.
const SAMPLING_RATE_KEY_PREFIX = '@posthog-test/logs-sampling-rate'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

/**
 * Mirror of `buildSamplingConfigPayload` (rate-limit branch) in the drop-rule form logic:
 * a byte rate in KB/s · MB/s · GB/s becomes `kb_per_second` + `burst_kb` (10× sustained).
 */
const UNIT_TO_KB = { 'KB/s': 1, 'MB/s': 1000, 'GB/s': 1_000_000 } as const
function rateLimitConfigLikeUI(amount: number, unit: keyof typeof UNIT_TO_KB): Record<string, unknown> {
    const kbPerSecond = Math.round(amount * UNIT_TO_KB[unit])
    return { kb_per_second: kbPerSecond, burst_kb: kbPerSecond * 10 }
}

function ruleSetForLimit(ruleId: string, amount: number, unit: keyof typeof UNIT_TO_KB) {
    return compileRuleSet([
        {
            id: ruleId,
            rule_type: 'rate_limit',
            scope_service: SERVICE,
            scope_path_pattern: null,
            scope_attribute_filters: [],
            config: rateLimitConfigLikeUI(amount, unit),
        },
    ])
}

function logRow(uuid: string, bytesUncompressed: number): LogRecord {
    return {
        uuid,
        trace_id: null,
        span_id: null,
        trace_flags: null,
        timestamp: 1_700_000_000_000_000,
        observed_timestamp: 1_700_000_000_000_000,
        body: 'x',
        severity_text: 'info',
        severity_number: 9,
        service_name: SERVICE,
        resource_attributes: null,
        instrumentation_scope: null,
        event_name: null,
        attributes: null,
        bytes_uncompressed: bytesUncompressed,
    }
}

describe('logs drop-rule rate limit — save-to-impact', () => {
    jest.retryTimes(3)

    let hub: Hub
    let redis: RedisV2
    let service: LogsSamplingService
    let now: number

    beforeEach(async () => {
        hub = await createHub()
        now = 1_720_000_000_000
        mockNow.mockReturnValue(now)

        redis = createRedisV2PoolFromConfig({
            connection: hub.LOGS_REDIS_HOST
                ? {
                      url: hub.LOGS_REDIS_HOST,
                      options: { port: hub.LOGS_REDIS_PORT, tls: hub.LOGS_REDIS_TLS ? {} : undefined },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        await deleteKeysWithPrefix(redis, SAMPLING_RATE_KEY_PREFIX)

        service = new LogsSamplingService(redis, 60 * 60 * 24)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    const advanceOneSecond = (): void => {
        now += 1000
        mockNow.mockReturnValue(now)
    }

    /** Push `recordsPerSecond` rows of `bytesEach` through one processBuffer call per simulated second. */
    async function streamForSeconds(
        ruleSet: ReturnType<typeof compileRuleSet>,
        seconds: number,
        recordsPerSecond: number,
        bytesEach: number
    ): Promise<{ dropped: number; kept: number }> {
        let dropped = 0
        let kept = 0
        for (let s = 0; s < seconds; s++) {
            const batch = Array.from({ length: recordsPerSecond }, (_, i) => logRow(`s${s}-r${i}`, bytesEach))
            const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', batch)
            const result = await service.processBuffer(buffer, logsSettings, ruleSet, TEAM_ID)
            dropped += result.recordsDropped
            kept += recordsPerSecond - result.recordsDropped
            advanceOneSecond()
        }
        return { dropped, kept }
    }

    // ~530 KB/s of real traffic — the order of magnitude smokescreen actually emits once the
    // 772× preview inflation is stripped out (530 rows/s × 1000 bytes).
    const RECORDS_PER_SECOND = 530
    const BYTES_EACH = 1000
    const SECONDS = 6

    it('a limit well above real volume (1 MB/s on ~530 KB/s) drops nothing', async () => {
        const ruleSet = ruleSetForLimit('rl-high', 1, 'MB/s') // kb_per_second: 1000 → ~1.02 MB/s
        const { dropped } = await streamForSeconds(ruleSet, SECONDS, RECORDS_PER_SECOND, BYTES_EACH)
        expect(dropped).toBe(0)
    })

    it('a limit well below real volume (50 KB/s on ~530 KB/s) sheds a large share', async () => {
        const ruleSet = ruleSetForLimit('rl-low', 50, 'KB/s') // kb_per_second: 50 → ~51 KB/s
        const { dropped } = await streamForSeconds(ruleSet, SECONDS, RECORDS_PER_SECOND, BYTES_EACH)
        // ~10× over the limit → a large share is dropped. We assert a robust floor rather than an
        // exact count: the per-batch token bucket admits somewhat above the nominal rate, but the
        // limit unambiguously bites (contrast the 1 MB/s case above, which drops nothing).
        expect(dropped).toBeGreaterThan(RECORDS_PER_SECOND * SECONDS * 0.3)
    })

    it('lowering the limit from 1 MB/s to 50 KB/s changes the impact (the reported regression)', async () => {
        // Before the form fix both values were written to `logs_per_second`, so the chosen byte rate
        // was ignored and lowering it did nothing. With the fix the threshold is enforced in bytes,
        // so the same stream is throttled far harder at 50 KB/s than at 1 MB/s.
        const high = await streamForSeconds(
            ruleSetForLimit('rl-cmp-high', 1, 'MB/s'),
            SECONDS,
            RECORDS_PER_SECOND,
            BYTES_EACH
        )
        await deleteKeysWithPrefix(redis, SAMPLING_RATE_KEY_PREFIX)
        const low = await streamForSeconds(
            ruleSetForLimit('rl-cmp-low', 50, 'KB/s'),
            SECONDS,
            RECORDS_PER_SECOND,
            BYTES_EACH
        )

        expect(high.dropped).toBe(0)
        expect(low.dropped).toBeGreaterThan(high.dropped)
    })

    it('only drops once the stream exceeds the configured byte rate', async () => {
        const ruleSet = ruleSetForLimit('rl-ramp', 100, 'KB/s') // ~102 KB/s sustained
        // 50 KB/s — comfortably under the limit → nothing dropped even over several seconds.
        const under = await streamForSeconds(ruleSet, SECONDS, 50, BYTES_EACH)
        expect(under.dropped).toBe(0)

        await deleteKeysWithPrefix(redis, SAMPLING_RATE_KEY_PREFIX)

        // 400 KB/s — ~4× over the limit → sustained drops.
        const over = await streamForSeconds(ruleSet, SECONDS, 400, BYTES_EACH)
        expect(over.dropped).toBeGreaterThan(0)

        // Decoding a sampled batch still yields valid avro (the kept rows re-encode cleanly).
        const batch = Array.from({ length: 400 }, (_, i) => logRow(`final-${i}`, BYTES_EACH))
        const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', batch)
        const result = await service.processBuffer(buffer, logsSettings, ruleSet, TEAM_ID)
        if (!result.allDropped) {
            const [, , kept] = await decodeLogRecords(result.value)
            expect(kept.length).toBe(400 - result.recordsDropped)
        }
    })
})
