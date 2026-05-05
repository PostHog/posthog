import { trace } from '@opentelemetry/api'

import { type RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { instrumented } from '~/common/tracing/tracing-utils'
import type { LogsSettings } from '~/types'

import { type PiiScrubStats } from '../log-pii-scrub'
import {
    type LogRecord,
    decodeLogRecords,
    encodeLogRecords,
    transformDecodedLogRecordsInPlace,
} from '../log-record-avro'
import type { CompiledRuleSet, RateLimitPendingByRule, SamplingClassifyResult } from './evaluate'
import {
    SAMPLING_DECISION_DROP,
    SAMPLING_DECISION_SAMPLE_DROPPED,
    classifySamplingRecord,
    evaluateLogRecord,
} from './evaluate'

const samplingProcessInstrumentOpts = { measureTime: false, sendException: false } as const

const SAMPLING_RATE_LIMIT_REDIS_PREFIX =
    process.env.NODE_ENV === 'test' ? '@posthog-test/logs-sampling-rate' : '@posthog/logs-sampling-rate'

export type SamplingRateContext = {
    teamId: number
    redis: RedisV2
    ttlSeconds: number
}

export type ProcessBufferWithSamplingResult = {
    value: Buffer
    pii: PiiScrubStats
    recordsDropped: number
    /** Counts dropped lines (drop / sample_dropped) attributed to the first matching rule UUID. */
    recordsDroppedByRuleId: Map<string, number>
    /** When true, the caller must not produce this message to downstream Kafka (all lines sampled out). */
    allDropped: boolean
}

async function applySamplingRateLimits(
    teamId: number,
    redis: RedisV2,
    ttlSeconds: number,
    ruleSet: CompiledRuleSet,
    pendingByRule: RateLimitPendingByRule,
    nowSeconds: number
): Promise<Map<number, boolean>> {
    /** recordIndex -> keep (true) or drop (false) when classification was rate_limit */
    const keepByIndex = new Map<number, boolean>()

    if (pendingByRule.size === 0) {
        return keepByIndex
    }

    const ruleById = new Map(ruleSet.rules.map((r) => [r.id, r]))
    const pipelineArgs: { ruleId: string; cost: number; poolMax: number; fillRate: number; key: string }[] = []

    for (const [ruleId, indices] of pendingByRule) {
        const rule = ruleById.get(ruleId)
        const rl = rule?.rateLimit
        if (!rl || indices.length === 0) {
            continue
        }
        pipelineArgs.push({
            ruleId,
            cost: indices.length,
            poolMax: rl.poolMax,
            fillRate: rl.refillPerSecond,
            key: `${SAMPLING_RATE_LIMIT_REDIS_PREFIX}/${teamId}/${ruleId}`,
        })
    }

    if (pipelineArgs.length === 0) {
        for (const [, indices] of pendingByRule) {
            for (const idx of indices) {
                keepByIndex.set(idx, true)
            }
        }
        return keepByIndex
    }

    const res = await redis.usePipeline({ name: 'logs-sampling-rate-limit', failOpen: true }, (pipeline) => {
        for (const a of pipelineArgs) {
            pipeline.checkRateLimitV2(a.key, nowSeconds, a.cost, a.poolMax, a.fillRate, ttlSeconds)
        }
    })

    if (!res) {
        for (const [, indices] of pendingByRule) {
            for (const idx of indices) {
                keepByIndex.set(idx, true)
            }
        }
        return keepByIndex
    }

    for (let pi = 0; pi < pipelineArgs.length; pi++) {
        const arg = pipelineArgs[pi]!
        const { ruleId, poolMax: argPoolMax } = arg
        const rule = ruleById.get(ruleId)
        const poolMax = rule?.rateLimit?.poolMax ?? argPoolMax
        const [tokenRes] = getRedisPipelineResults(res, pi, 1)
        const tokensBefore = Number(tokenRes[1]?.[0] ?? poolMax)
        const indices = pendingByRule.get(ruleId) ?? []
        const budget = Math.max(0, Math.floor(tokensBefore))
        const toAdmit = Math.min(indices.length, budget)
        for (let j = 0; j < indices.length; j++) {
            keepByIndex.set(indices[j]!, j < toAdmit)
        }
    }

    return keepByIndex
}

async function processBufferWithSamplingImpl(
    buffer: Buffer,
    settings: LogsSettings,
    ruleSet: CompiledRuleSet,
    rateCtx?: SamplingRateContext | null
): Promise<ProcessBufferWithSamplingResult> {
    const [logRecordType, compressionCodec, records] = await decodeLogRecords(buffer)
    if (!logRecordType) {
        throw new Error('avro schema metadata not found')
    }
    const pii = await transformDecodedLogRecordsInPlace(records, settings)
    const kept: LogRecord[] = []
    let recordsDropped = 0
    const recordsDroppedByRuleId = new Map<string, number>()

    const useRate = Boolean(ruleSet.hasRateLimitRules && rateCtx)

    if (useRate && rateCtx) {
        const classifications: SamplingClassifyResult[] = records.map((r) => classifySamplingRecord(ruleSet, r))
        const pendingByRule: RateLimitPendingByRule = new Map()
        for (let i = 0; i < records.length; i++) {
            const c = classifications[i]!
            if (c.kind === 'rate_limit') {
                const list = pendingByRule.get(c.ruleId) ?? []
                list.push(i)
                pendingByRule.set(c.ruleId, list)
            }
        }
        const nowSeconds = Math.floor(Date.now() / 1000)
        const rateKeep = await applySamplingRateLimits(
            rateCtx.teamId,
            rateCtx.redis,
            rateCtx.ttlSeconds,
            ruleSet,
            pendingByRule,
            nowSeconds
        )

        for (let i = 0; i < records.length; i++) {
            const record = records[i]!
            const c = classifications[i]!
            if (c.kind === 'rate_limit') {
                const allow = rateKeep.get(i) !== false
                if (!allow) {
                    recordsDropped++
                    recordsDroppedByRuleId.set(c.ruleId, (recordsDroppedByRuleId.get(c.ruleId) ?? 0) + 1)
                    continue
                }
                kept.push(record)
                continue
            }
            if (c.decision === SAMPLING_DECISION_DROP || c.decision === SAMPLING_DECISION_SAMPLE_DROPPED) {
                recordsDropped++
                if (c.ruleId != null) {
                    recordsDroppedByRuleId.set(c.ruleId, (recordsDroppedByRuleId.get(c.ruleId) ?? 0) + 1)
                }
                continue
            }
            kept.push(record)
        }
    } else {
        for (const record of records) {
            const { decision, ruleId } = evaluateLogRecord(ruleSet, record)
            if (decision === SAMPLING_DECISION_DROP || decision === SAMPLING_DECISION_SAMPLE_DROPPED) {
                recordsDropped++
                if (ruleId != null) {
                    recordsDroppedByRuleId.set(ruleId, (recordsDroppedByRuleId.get(ruleId) ?? 0) + 1)
                }
                continue
            }
            kept.push(record)
        }
    }

    trace.getActiveSpan()?.setAttributes({
        'logs.sampling.input_record_count': records.length,
        'logs.sampling.kept_record_count': kept.length,
        'logs.sampling.dropped_record_count': recordsDropped,
        'logs.sampling.all_dropped': kept.length === 0,
        'logs.sampling.json_parse_logs': Boolean(settings.json_parse_logs),
        'logs.sampling.pii_scrub_logs': Boolean(settings.pii_scrub_logs),
    })

    if (kept.length === 0) {
        return { value: Buffer.alloc(0), pii, recordsDropped, recordsDroppedByRuleId, allDropped: true }
    }
    const value = await encodeLogRecords(logRecordType, compressionCodec, kept)
    return { value, pii, recordsDropped, recordsDroppedByRuleId, allDropped: false }
}

export const processBufferWithSampling = instrumented({
    key: 'logsIngestion.sampling.processBufferWithSampling',
    ...samplingProcessInstrumentOpts,
})(processBufferWithSamplingImpl)
