import avro from 'avsc'

import type { RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'
import { type LogRecord, decodeLogRecords, encodeLogRecords } from '~/logs/log-record-avro'
import type { LogsSettings } from '~/types'

import { compileRuleSet } from './compile-rules'
import { LogsSamplingService } from './logs-sampling.service'

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

const logsSettings: LogsSettings = { json_parse_logs: false, pii_scrub_logs: false }

function baseLog(uuid: string, serviceName: string, bytesUncompressed: number | null = null): LogRecord {
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
        service_name: serviceName,
        resource_attributes: null,
        instrumentation_scope: null,
        event_name: null,
        attributes: null,
        bytes_uncompressed: bytesUncompressed,
    }
}

describe('LogsSamplingService', () => {
    it('batches rate_limit lines and drops when tokensBefore is below pending count', async () => {
        const ruleSet = compileRuleSet([
            {
                id: 'rl-1',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { logs_per_second: 100, burst_logs: 1000 },
            },
        ])
        const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', [
            baseLog('a', 'api', 100),
            baseLog('b', 'api', 100),
            baseLog('c', 'api', 100),
        ])

        const mockRedis: RedisV2 = {
            useClient: jest.fn(() => Promise.resolve(null)),
            usePipeline: jest.fn((_opts, cb) => {
                const pipeline = { checkRateLimitV3: jest.fn() } as unknown as RedisClientPipeline
                cb(pipeline)
                const pipelineResult: [Error | null, any][] = [[null, [2, 0] as const]]
                return Promise.resolve(pipelineResult)
            }),
        }

        const service = new LogsSamplingService(mockRedis, 60)
        const result = await service.processBuffer(buffer, logsSettings, ruleSet, 99)

        expect(result.recordsDropped).toBe(1)
        expect(result.recordsDroppedByRuleId.get('rl-1')).toBe(1)
        // Each row is fixtured at 100 bytes; the one dropped row contributes 100.
        expect(result.bytesDropped).toBe(100)
        expect(result.bytesDroppedByRuleId.get('rl-1')).toBe(100)
        expect(result.allDropped).toBe(false)

        const [, , kept] = await decodeLogRecords(result.value)
        expect(kept).toHaveLength(2)
    })

    it('attributes per-row bytes to the dropping rule and contributes 0 for null bytes_uncompressed', async () => {
        const ruleSet = compileRuleSet([
            {
                id: 'rl-1',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { logs_per_second: 100, burst_logs: 1000 },
            },
        ])
        // 3 rows: 250 bytes, 750 bytes, null (old-producer message).
        // Token budget of 1 → first row admitted, the other two dropped.
        const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', [
            baseLog('a', 'api', 250),
            baseLog('b', 'api', 750),
            baseLog('c', 'api', null),
        ])

        const mockRedis: RedisV2 = {
            useClient: jest.fn(() => Promise.resolve(null)),
            usePipeline: jest.fn((_opts, cb) => {
                const pipeline = { checkRateLimitV3: jest.fn() } as unknown as RedisClientPipeline
                cb(pipeline)
                const pipelineResult: [Error | null, any][] = [[null, [1, 0] as const]]
                return Promise.resolve(pipelineResult)
            }),
        }

        const service = new LogsSamplingService(mockRedis, 60)
        const result = await service.processBuffer(buffer, logsSettings, ruleSet, 99)

        expect(result.recordsDropped).toBe(2)
        // Only the row with a populated bytes_uncompressed contributes to the byte sum;
        // the null row falls back to 0 (in-flight transition behavior).
        expect(result.bytesDropped).toBe(750)
        expect(result.bytesDroppedByRuleId.get('rl-1')).toBe(750)
    })

    it('KB-mode admits records while accumulated bytes fit the budget', async () => {
        const ruleSet = compileRuleSet([
            {
                id: 'rl-kb',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { kb_per_second: 1, burst_kb: 2 },
            },
        ])
        // 3 rows of 300, 400, 500 bytes. Budget = 1024 bytes (1 KB).
        // Walk: 300 ≤ 1024 (admit), 300+400 ≤ 1024 (admit), 700+500 > 1024 (drop).
        const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', [
            baseLog('a', 'api', 300),
            baseLog('b', 'api', 400),
            { ...baseLog('c', 'api', 500), attributes: { k: 'vv' }, event_name: 'evt' },
        ])

        const mockRedis: RedisV2 = {
            useClient: jest.fn(() => Promise.resolve(null)),
            usePipeline: jest.fn((_opts, cb) => {
                const pipeline = { checkRateLimitV3: jest.fn() } as unknown as RedisClientPipeline
                cb(pipeline)
                const pipelineResult: [Error | null, any][] = [[null, [1024, 0] as const]]
                return Promise.resolve(pipelineResult)
            }),
        }

        const service = new LogsSamplingService(mockRedis, 60)
        const result = await service.processBuffer(buffer, logsSettings, ruleSet, 99)

        expect(result.recordsDropped).toBe(1)
        expect(result.recordsDroppedByRuleId.get('rl-kb')).toBe(1)
        expect(result.bytesDropped).toBe(500)
        expect(result.bytesDroppedByRuleId.get('rl-kb')).toBe(500)
        // Billing pro-rate weights are customer-content bytes (body + attributes + event_name),
        // independent of the per-row bytes_uncompressed field used for rate limiting:
        // rows a,b = body 'x' (1 each); dropped row c = body(1) + attrs 'k'+'vv'(3) + 'evt'(3) = 7.
        expect(result.contentBytesTotal).toBe(9)
        expect(result.contentBytesDropped).toBe(7)

        const [, , kept] = await decodeLogRecords(result.value)
        expect(kept).toHaveLength(2)
    })

    it('KB-mode treats null bytes_uncompressed as zero-cost (in-flight producer rollout)', async () => {
        const ruleSet = compileRuleSet([
            {
                id: 'rl-kb',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { kb_per_second: 1, burst_kb: 2 },
            },
        ])
        // Rows: 200, null (old-producer message), 1000. Budget = 1024.
        // Walk: 200 (admit), 200+0 = 200 (admit), 200+1000 > 1024 (drop).
        const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', [
            baseLog('a', 'api', 200),
            baseLog('b', 'api', null),
            baseLog('c', 'api', 1000),
        ])

        const mockRedis: RedisV2 = {
            useClient: jest.fn(() => Promise.resolve(null)),
            usePipeline: jest.fn((_opts, cb) => {
                const pipeline = { checkRateLimitV3: jest.fn() } as unknown as RedisClientPipeline
                cb(pipeline)
                const pipelineResult: [Error | null, any][] = [[null, [1024, 0] as const]]
                return Promise.resolve(pipelineResult)
            }),
        }

        const service = new LogsSamplingService(mockRedis, 60)
        const result = await service.processBuffer(buffer, logsSettings, ruleSet, 99)

        expect(result.recordsDropped).toBe(1)
        expect(result.bytesDropped).toBe(1000)
        expect(result.bytesDroppedByRuleId.get('rl-kb')).toBe(1000)
        // Content weights don't depend on the per-row bytes_uncompressed field at all:
        // the null-field row still weighs its body bytes (1 each, 3 rows, 1 dropped).
        expect(result.contentBytesTotal).toBe(3)
        expect(result.contentBytesDropped).toBe(1)

        const [, , kept] = await decodeLogRecords(result.value)
        expect(kept).toHaveLength(2)
    })

    it('KB-mode meters each row against its pro-rata share of the batch header, not per-row bytes_uncompressed', async () => {
        const ruleSet = compileRuleSet([
            {
                id: 'rl-kb',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { kb_per_second: 1, burst_kb: 2 },
            },
        ])
        // Per-row bytes_uncompressed is inflated (900 each) because shared batch data is
        // re-counted on every row; content bytes (body only here) are 2/4/6 → total 12.
        // Header = 24 → pro-rata scale 2 → per-row cost 4/8/12. Budget = 12:
        // 4 (admit), 4+8=12 (admit), 12+12=24 > 12 (drop row c). Metering on the raw
        // bytes_uncompressed sum (900 each) would have dropped every row.
        const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', [
            { ...baseLog('a', 'api', 900), body: 'aa' },
            { ...baseLog('b', 'api', 900), body: 'bbbb' },
            { ...baseLog('c', 'api', 900), body: 'cccccc' },
        ])

        const checkRateLimitV3 = jest.fn()
        const mockRedis: RedisV2 = {
            useClient: jest.fn(() => Promise.resolve(null)),
            usePipeline: jest.fn((_opts, cb) => {
                cb({ checkRateLimitV3 } as unknown as RedisClientPipeline)
                const pipelineResult: [Error | null, any][] = [[null, [12, 0] as const]]
                return Promise.resolve(pipelineResult)
            }),
        }

        const service = new LogsSamplingService(mockRedis, 60)
        const result = await service.processBuffer(buffer, logsSettings, ruleSet, 99, 24)

        // The batch is metered at the header pro-rata total (= header bytes), not Σ bytes_uncompressed.
        // Args are [key, now, cost, bucketSize, refillRate, ttl]; cost is index 2.
        expect(checkRateLimitV3.mock.calls[0]![2]).toBe(24)
        expect(result.recordsDropped).toBe(1)
        expect(result.recordsDroppedByRuleId.get('rl-kb')).toBe(1)
        // The dropped-bytes metric still reports the row's real bytes_uncompressed.
        expect(result.bytesDropped).toBe(900)

        const [, , kept] = await decodeLogRecords(result.value)
        expect(kept).toHaveLength(2)
    })

    it('fail-open keeps all rate_limit lines when Redis pipeline returns null', async () => {
        const ruleSet = compileRuleSet([
            {
                id: 'rl-1',
                rule_type: 'rate_limit',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { logs_per_second: 10 },
            },
        ])
        const buffer = await encodeLogRecords(LOG_RECORD_AVRO, 'zstandard', [baseLog('a', 'api'), baseLog('b', 'api')])

        const mockRedis: RedisV2 = {
            useClient: jest.fn(() => Promise.resolve(null)),
            usePipeline: jest.fn(() => Promise.resolve(null)),
        }

        const service = new LogsSamplingService(mockRedis, 60)
        const result = await service.processBuffer(buffer, logsSettings, ruleSet, 1)

        expect(result.recordsDropped).toBe(0)
        expect(result.recordsDroppedByRuleId.size).toBe(0)
        expect(result.bytesDropped).toBe(0)
        expect(result.bytesDroppedByRuleId.size).toBe(0)

        const [, , kept] = await decodeLogRecords(result.value)
        expect(kept).toHaveLength(2)
    })
})
