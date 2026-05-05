import avro from 'avsc'

import type { RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'
import type { LogsSettings } from '~/types'

import { type LogRecord, decodeLogRecords, encodeLogRecords } from '../log-record-avro'
import { compileRuleSet } from './compile-rules'
import { type SamplingRateContext, processBufferWithSampling } from './process-buffer-with-sampling'

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
    ],
})

const logsSettings: LogsSettings = { json_parse_logs: false, pii_scrub_logs: false }

function baseLog(uuid: string, serviceName: string): LogRecord {
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
    }
}

describe('processBufferWithSampling', () => {
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
            baseLog('a', 'api'),
            baseLog('b', 'api'),
            baseLog('c', 'api'),
        ])

        const mockRedis: RedisV2 = {
            useClient: jest.fn(() => Promise.resolve(null)),
            usePipeline: jest.fn((_opts, cb) => {
                const pipeline = { checkRateLimitV2: jest.fn() } as unknown as RedisClientPipeline
                cb(pipeline)
                const pipelineResult: [Error | null, any][] = [[null, [2, 0] as const]]
                return Promise.resolve(pipelineResult)
            }),
        }

        const rateCtx: SamplingRateContext = { teamId: 99, redis: mockRedis, ttlSeconds: 60 }
        const result = await processBufferWithSampling(buffer, logsSettings, ruleSet, rateCtx)

        expect(result.recordsDropped).toBe(1)
        expect(result.recordsDroppedByRuleId.get('rl-1')).toBe(1)
        expect(result.allDropped).toBe(false)

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

        const rateCtx: SamplingRateContext = { teamId: 1, redis: mockRedis, ttlSeconds: 60 }
        const result = await processBufferWithSampling(buffer, logsSettings, ruleSet, rateCtx)

        expect(result.recordsDropped).toBe(0)
        expect(result.recordsDroppedByRuleId.size).toBe(0)

        const [, , kept] = await decodeLogRecords(result.value)
        expect(kept).toHaveLength(2)
    })
})
