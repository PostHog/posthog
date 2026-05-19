import { trace } from '@opentelemetry/api'

import { type RedisV2 } from '~/common/redis/redis-v2'
import { KeyedRateLimitRequest, KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'
import { instrumented } from '~/common/tracing/tracing-utils'
import type { LogsSettings } from '~/types'

import { type PiiScrubStats } from '../log-pii-scrub'
import {
    type LogRecord,
    decodeLogRecords,
    encodeLogRecords,
    transformDecodedLogRecordsInPlace,
} from '../log-record-avro'
import type { CompiledRuleSet, RateLimitPendingByRule } from './evaluate'
import {
    SAMPLING_DECISION_DROP,
    SAMPLING_DECISION_SAMPLE_DROPPED,
    classifySamplingRecord,
    evaluateLogRecord,
} from './evaluate'

export type ProcessBufferWithSamplingResult = {
    value: Buffer
    pii: PiiScrubStats
    recordsDropped: number
    /** Counts dropped lines (drop / sample_dropped) attributed to the first matching rule UUID. */
    recordsDroppedByRuleId: Map<string, number>
    /** When true, the caller must not produce this message to downstream Kafka (all lines sampled out). */
    allDropped: boolean
}

export class LogsSamplingService {
    private rateLimiter: KeyedRateLimiterService

    constructor(redis: RedisV2, ttlSeconds: number) {
        this.rateLimiter = new KeyedRateLimiterService({ name: 'logs-sampling-rate', ttlSeconds }, redis)
    }

    @instrumented({
        key: 'logsIngestion.sampling.processBufferWithSampling',
        measureTime: false,
        sendException: false,
    })
    public async processBuffer(
        buffer: Buffer,
        settings: LogsSettings,
        ruleSet: CompiledRuleSet,
        teamId?: number
    ): Promise<ProcessBufferWithSamplingResult> {
        const [logRecordType, compressionCodec, records] = await decodeLogRecords(buffer)
        if (!logRecordType) {
            throw new Error('avro schema metadata not found')
        }
        const pii = await transformDecodedLogRecordsInPlace(records, settings)
        const kept: LogRecord[] = []
        let recordsDropped = 0
        const recordsDroppedByRuleId = new Map<string, number>()

        const useRate = Boolean(ruleSet.hasRateLimitRules && teamId != null)

        if (useRate && teamId != null) {
            const classifications = records.map((r) => classifySamplingRecord(ruleSet, r))
            const pendingByRule: RateLimitPendingByRule = new Map()
            for (let i = 0; i < records.length; i++) {
                const c = classifications[i]!
                if (c.kind === 'rate_limit') {
                    const list = pendingByRule.get(c.ruleId) ?? []
                    list.push(i)
                    pendingByRule.set(c.ruleId, list)
                }
            }
            const rateKeep = await this.applyRateLimits(teamId, ruleSet, pendingByRule)

            for (let i = 0; i < records.length; i++) {
                const record = records[i]!
                const c = classifications[i]!
                if (c.kind === 'rate_limit') {
                    if (rateKeep.get(i) === false) {
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

    /**
     * Maps a recordIndex -> keep (true) or drop (false) decision per rate_limit rule.
     * Each rule's pending lines share one Lua call; lines are admitted up to the
     * pre-batch token budget.
     */
    private async applyRateLimits(
        teamId: number,
        ruleSet: CompiledRuleSet,
        pendingByRule: RateLimitPendingByRule
    ): Promise<Map<number, boolean>> {
        const keepByIndex = new Map<number, boolean>()
        if (pendingByRule.size === 0) {
            return keepByIndex
        }

        const ruleById = new Map(ruleSet.rules.map((r) => [r.id, r]))
        type Entry = { indices: number[]; req: KeyedRateLimitRequest }
        const entries: Entry[] = []

        for (const [ruleId, indices] of pendingByRule) {
            const rl = ruleById.get(ruleId)?.rateLimit
            if (!rl || indices.length === 0) {
                continue
            }
            entries.push({
                indices,
                req: {
                    id: `${teamId}/${ruleId}`,
                    cost: indices.length,
                    bucketSize: rl.poolMax,
                    refillRate: rl.refillPerSecond,
                },
            })
        }

        if (entries.length === 0) {
            for (const [, indices] of pendingByRule) {
                for (const idx of indices) {
                    keepByIndex.set(idx, true)
                }
            }
            return keepByIndex
        }

        const results = await this.rateLimiter.rateLimitMany(entries.map((e) => e.req))

        for (let i = 0; i < entries.length; i++) {
            const { indices } = entries[i]!
            const tokensBefore = results[i]?.[1].tokensBefore ?? 0
            const budget = Math.max(0, Math.floor(tokensBefore))
            const toAdmit = Math.min(indices.length, budget)
            for (let j = 0; j < indices.length; j++) {
                keepByIndex.set(indices[j]!, j < toAdmit)
            }
        }

        return keepByIndex
    }
}
