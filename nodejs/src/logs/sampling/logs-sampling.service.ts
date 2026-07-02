import { trace } from '@opentelemetry/api'
import { Counter } from 'prom-client'

import { type RedisV2 } from '~/common/redis/redis-v2'
import { KeyedRateLimitRequest, KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'
import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { type PiiScrubStats } from '~/logs/log-pii-scrub'
import {
    type LogRecord,
    type LogRecordsTransform,
    decodeLogRecords,
    encodeLogRecords,
    transformDecodedLogRecordsInPlace,
} from '~/logs/log-record-avro'
import type { LogsSettings } from '~/types'

import type { CompiledRuleSet, EvaluateResult, RateLimitPendingByRule, SamplingClassifyResult } from './evaluate'
import {
    SAMPLING_DECISION_DROP,
    SAMPLING_DECISION_KEEP,
    SAMPLING_DECISION_SAMPLE_DROPPED,
    classifySamplingRecord,
    evaluateLogRecord,
} from './evaluate'

/**
 * Incremented when a per-record sampling evaluation throws. The record is kept
 * (fail-open) so an adversarial or malformed rule cannot drop traffic via an
 * uncaught exception, but the counter makes the silent failure observable.
 */
export const logsSamplingEvalErrorCounter = new Counter({
    name: 'logs_ingestion_sampling_eval_error_total',
    help: 'Per-record sampling evaluation threw an exception; record was kept (fail-open).',
    labelNames: ['team_id', 'phase'],
})

function safeClassifySamplingRecord(
    ruleSet: CompiledRuleSet,
    record: LogRecord,
    teamId: number
): SamplingClassifyResult {
    try {
        return classifySamplingRecord(ruleSet, record)
    } catch (err) {
        logsSamplingEvalErrorCounter.inc({ team_id: String(teamId), phase: 'classify' })
        logger.warn('[logs-sampling] classifySamplingRecord threw — keeping record', { teamId, err })
        return { kind: 'resolved', decision: SAMPLING_DECISION_KEEP, ruleId: null }
    }
}

function safeEvaluateLogRecord(ruleSet: CompiledRuleSet, record: LogRecord, teamId: number): EvaluateResult {
    try {
        return evaluateLogRecord(ruleSet, record)
    } catch (err) {
        logsSamplingEvalErrorCounter.inc({ team_id: String(teamId), phase: 'evaluate' })
        logger.warn('[logs-sampling] evaluateLogRecord threw — keeping record', { teamId, err })
        return { decision: SAMPLING_DECISION_KEEP, ruleId: null }
    }
}

export type ProcessBufferWithSamplingResult = {
    value: Buffer
    pii: PiiScrubStats
    recordsDropped: number
    /** Counts dropped lines (drop / sample_dropped) attributed to the first matching rule UUID. */
    recordsDroppedByRuleId: Map<string, number>
    /** Sum of per-row `bytes_uncompressed` for dropped lines. Rows from old producers contribute 0. */
    bytesDropped: number
    /** Sum of per-row `bytes_uncompressed` for dropped lines, attributed to the first matching rule UUID. */
    bytesDroppedByRuleId: Map<string, number>
    /** Sum of customer-content bytes (body + attributes + event_name) for dropped lines. Billing pro-rate numerator. */
    contentBytesDropped: number
    /** Sum of customer-content bytes across ALL decoded rows (kept + dropped). Billing pro-rate denominator. */
    contentBytesTotal: number
    /** When true, the caller must not produce this message to downstream Kafka (all lines removed). */
    allDropped: boolean
    /** What removed the final surviving lines when `allDropped` is true. */
    allDroppedBy?: 'sampling' | 'transformations'
}

const recordBytes = (r: LogRecord): number => r.bytes_uncompressed ?? 0

/**
 * Customer-sent content bytes of a row: body + attributes + event_name. The billing
 * pro-rate weight — deliberately NOT `bytes_uncompressed`, which includes per-row
 * denormalization overhead (resource attributes duplicated onto every row, server
 * uuid, id placeholders). That overhead is near-constant per row, so as a ratio
 * weight it would skew the pro-rate toward record-count weighting instead of
 * "share of what the customer sent".
 */
const contentBytes = (r: LogRecord): number => {
    let total = Buffer.byteLength(r.body ?? '') + Buffer.byteLength(r.event_name ?? '')
    for (const [k, v] of Object.entries(r.attributes ?? {})) {
        total += Buffer.byteLength(k) + Buffer.byteLength(v ?? '')
    }
    return total
}

export class LogsSamplingService {
    private rateLimiter: KeyedRateLimiterService

    constructor(redis: RedisV2, ttlSeconds: number) {
        this.rateLimiter = new KeyedRateLimiterService(
            { name: 'logs-sampling-rate', ttlSeconds, scriptVersion: 'v3' },
            redis
        )
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
        teamId?: number,
        headerBytesUncompressed: number = 0,
        recordsTransform?: LogRecordsTransform
    ): Promise<ProcessBufferWithSamplingResult> {
        const [logRecordType, compressionCodec, records] = await decodeLogRecords(buffer)
        if (!logRecordType) {
            throw new Error('avro schema metadata not found')
        }
        const pii = await transformDecodedLogRecordsInPlace(records, settings)
        const kept: LogRecord[] = []
        let recordsDropped = 0
        const recordsDroppedByRuleId = new Map<string, number>()
        let bytesDropped = 0
        const bytesDroppedByRuleId = new Map<string, number>()
        let contentBytesDropped = 0
        const contentBytesTotal = records.reduce((sum, r) => sum + contentBytes(r), 0)

        const useRate = Boolean(ruleSet.hasRateLimitRules && teamId != null)

        if (useRate && teamId != null) {
            const classifications = records.map((r) => safeClassifySamplingRecord(ruleSet, r, teamId))
            const pendingByRule: RateLimitPendingByRule = new Map()
            for (let i = 0; i < records.length; i++) {
                const c = classifications[i]!
                if (c.kind === 'rate_limit') {
                    const list = pendingByRule.get(c.ruleId) ?? []
                    list.push(i)
                    pendingByRule.set(c.ruleId, list)
                }
            }
            const rateKeep = await this.applyRateLimits(
                teamId,
                ruleSet,
                pendingByRule,
                records,
                headerBytesUncompressed,
                contentBytesTotal
            )

            for (let i = 0; i < records.length; i++) {
                const record = records[i]!
                const c = classifications[i]!
                if (c.kind === 'rate_limit') {
                    if (rateKeep.get(i) === false) {
                        const rb = recordBytes(record)
                        recordsDropped++
                        bytesDropped += rb
                        contentBytesDropped += contentBytes(record)
                        recordsDroppedByRuleId.set(c.ruleId, (recordsDroppedByRuleId.get(c.ruleId) ?? 0) + 1)
                        bytesDroppedByRuleId.set(c.ruleId, (bytesDroppedByRuleId.get(c.ruleId) ?? 0) + rb)
                        continue
                    }
                    kept.push(record)
                    continue
                }
                if (c.decision === SAMPLING_DECISION_DROP || c.decision === SAMPLING_DECISION_SAMPLE_DROPPED) {
                    const rb = recordBytes(record)
                    recordsDropped++
                    bytesDropped += rb
                    contentBytesDropped += contentBytes(record)
                    if (c.ruleId != null) {
                        recordsDroppedByRuleId.set(c.ruleId, (recordsDroppedByRuleId.get(c.ruleId) ?? 0) + 1)
                        bytesDroppedByRuleId.set(c.ruleId, (bytesDroppedByRuleId.get(c.ruleId) ?? 0) + rb)
                    }
                    continue
                }
                kept.push(record)
            }
        } else {
            for (const record of records) {
                const { decision, ruleId } = safeEvaluateLogRecord(ruleSet, record, teamId ?? 0)
                if (decision === SAMPLING_DECISION_DROP || decision === SAMPLING_DECISION_SAMPLE_DROPPED) {
                    const rb = recordBytes(record)
                    recordsDropped++
                    bytesDropped += rb
                    contentBytesDropped += contentBytes(record)
                    if (ruleId != null) {
                        recordsDroppedByRuleId.set(ruleId, (recordsDroppedByRuleId.get(ruleId) ?? 0) + 1)
                        bytesDroppedByRuleId.set(ruleId, (bytesDroppedByRuleId.get(ruleId) ?? 0) + rb)
                    }
                    continue
                }
                kept.push(record)
            }
        }

        // Hog log transformations run last, on the records that survived the drop rules
        let keptBeforeTransform = 0
        if (recordsTransform && kept.length > 0) {
            keptBeforeTransform = kept.length
            await recordsTransform(kept)
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
            return {
                value: Buffer.alloc(0),
                pii,
                recordsDropped,
                recordsDroppedByRuleId,
                bytesDropped,
                bytesDroppedByRuleId,
                contentBytesDropped,
                contentBytesTotal,
                allDropped: true,
                // Sampling left survivors and the transform removed the rest — attribute
                // the full-message drop to transformations, not the drop rules.
                allDroppedBy: keptBeforeTransform > 0 ? 'transformations' : 'sampling',
            }
        }
        const value = await encodeLogRecords(logRecordType, compressionCodec, kept)
        return {
            value,
            pii,
            recordsDropped,
            recordsDroppedByRuleId,
            bytesDropped,
            bytesDroppedByRuleId,
            contentBytesDropped,
            contentBytesTotal,
            allDropped: false,
        }
    }

    /**
     * Maps a recordIndex -> keep (true) or drop (false) decision per rate_limit rule.
     * Each rule's pending lines share one Lua call; lines are admitted while their
     * accumulated cost stays within the pre-batch token budget. Cost is one token
     * per record (`costUnit: 'records'`) or, for `costUnit: 'bytes'`, each row's
     * pro-rata share of the batch header `bytesUncompressed`
     * (`headerBytesUncompressed × contentBytes(row) / contentBytesTotal`) — the same
     * unit billing meters, so the limiter admits at the configured byte rate instead
     * of over-counting the per-row `bytes_uncompressed` (which re-includes shared
     * batch data on every row). Falls back to per-row `bytes_uncompressed` when the
     * header is unavailable (older producers).
     */
    private async applyRateLimits(
        teamId: number,
        ruleSet: CompiledRuleSet,
        pendingByRule: RateLimitPendingByRule,
        records: LogRecord[],
        headerBytesUncompressed: number,
        contentBytesTotal: number
    ): Promise<Map<number, boolean>> {
        const keepByIndex = new Map<number, boolean>()
        if (pendingByRule.size === 0) {
            return keepByIndex
        }

        const proRataScale =
            headerBytesUncompressed > 0 && contentBytesTotal > 0 ? headerBytesUncompressed / contentBytesTotal : 0
        const byteCost = (idx: number): number =>
            proRataScale > 0 ? contentBytes(records[idx]!) * proRataScale : recordBytes(records[idx]!)

        const ruleById = new Map(ruleSet.rules.map((r) => [r.id, r]))
        type Entry = { indices: number[]; costs: number[]; req: KeyedRateLimitRequest }
        const entries: Entry[] = []

        for (const [ruleId, indices] of pendingByRule) {
            const rl = ruleById.get(ruleId)?.rateLimit
            if (!rl || indices.length === 0) {
                continue
            }
            const costs = rl.costUnit === 'bytes' ? indices.map(byteCost) : indices.map(() => 1)
            const totalCost = costs.reduce((a, b) => a + b, 0)
            entries.push({
                indices,
                costs,
                req: {
                    id: `${teamId}/${ruleId}`,
                    cost: totalCost,
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
            const { indices, costs } = entries[i]!
            const tokensBefore = results[i]?.[1].tokensBefore ?? 0
            const budget = Math.max(0, Math.floor(tokensBefore))
            let spent = 0
            for (let j = 0; j < indices.length; j++) {
                const next = spent + costs[j]!
                const admit = next <= budget
                keepByIndex.set(indices[j]!, admit)
                if (admit) {
                    spent = next
                }
            }
        }

        return keepByIndex
    }
}
