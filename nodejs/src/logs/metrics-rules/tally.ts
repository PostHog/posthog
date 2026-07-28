import type { LogRecord } from '../log-record-avro'
import { matchFilterGroup } from '../sampling/filter-group-match'
import type { CompiledMetricRule } from './compile-metric-rules'

/** Cap on distinct group-by label sets per rule per batch — bounds emitted series cardinality. */
export const MAX_LABEL_SETS_PER_RULE = 1000

export const MAX_LABEL_VALUE_LENGTH = 256

/**
 * Records with timestamps older than this never feed a metric, so a backfill of
 * historical logs cannot distort the "now" data point (matches Datadog's 20-minute
 * aggregation window for log-based metrics).
 */
export const MAX_RECORD_AGE_MS = 20 * 60 * 1000

export type MetricTallyEntry = {
    /** Group-by values in the rule's `groupBy` key order. */
    labelValues: string[]
    count: number
    sum: number
    exemplarTraceId: string | null
    exemplarSpanId: string | null
}

export type BatchTallies = {
    byRule: Map<string, Map<string, MetricTallyEntry>>
    /** Records that matched but were dropped because the rule hit MAX_LABEL_SETS_PER_RULE. */
    seriesOverflow: Map<string, number>
    /** Records that matched a value-attribute rule but carried a missing/non-numeric value. */
    valueSkipped: number
    /** Per-record filter evaluations that threw; the record is skipped for that rule only. */
    evalErrors: number
}

export function createBatchTallies(): BatchTallies {
    return { byRule: new Map(), seriesOverflow: new Map(), valueSkipped: 0, evalErrors: 0 }
}

const ATTRIBUTES_PREFIX = 'attributes.'
const RESOURCE_ATTRIBUTES_PREFIX = 'resource_attributes.'

function lookupKey(key: string, record: LogRecord): string | null | undefined {
    if (key === 'service_name') {
        return record.service_name
    }
    if (key === 'severity_text') {
        return record.severity_text
    }
    if (key === 'event_name') {
        return record.event_name
    }
    if (key.startsWith(ATTRIBUTES_PREFIX)) {
        return record.attributes?.[key.slice(ATTRIBUTES_PREFIX.length)]
    }
    if (key.startsWith(RESOURCE_ATTRIBUTES_PREFIX)) {
        return record.resource_attributes?.[key.slice(RESOURCE_ATTRIBUTES_PREFIX.length)]
    }
    return undefined
}

function resolveLabelValue(key: string, record: LogRecord): string {
    const value = lookupKey(key, record) ?? ''
    return value.length > MAX_LABEL_VALUE_LENGTH ? value.slice(0, MAX_LABEL_VALUE_LENGTH) : value
}

function resolveNumericValue(key: string, record: LogRecord): number | null {
    const raw = lookupKey(key, record)
    if (raw == null || raw === '') {
        return null
    }
    const parsed = parseFloat(raw)
    return Number.isFinite(parsed) ? parsed : null
}

/**
 * Normalizes a trace/span id from the log Avro into lowercase hex, or null when absent,
 * zeroed, or unparseable. capture-logs writes these fields as base64 TEXT of the raw
 * bytes (not the bytes themselves), so decode when the length doesn't match; raw-byte
 * buffers (tests, future producers) pass through unchanged.
 */
function idToHex(buffer: Buffer | null, expectedBytes: number): string | null {
    if (!buffer || buffer.length === 0) {
        return null
    }
    let bytes = buffer
    if (bytes.length !== expectedBytes) {
        const decoded = Buffer.from(bytes.toString('ascii'), 'base64')
        if (decoded.length !== expectedBytes) {
            return null
        }
        bytes = decoded
    }
    if (!bytes.some((byte) => byte !== 0)) {
        return null
    }
    return bytes.toString('hex')
}

/**
 * Evaluates every rule against every record and accumulates per-(rule, label set)
 * count/sum into `tallies`. Pure accumulation — no I/O, no clock reads (`nowMs` is
 * injected). Any single-record failure is contained: filter evaluation throwing or a
 * non-numeric value skips that record for that rule and increments a tally counter.
 */
export function tallyRecords(
    rules: CompiledMetricRule[],
    records: LogRecord[],
    tallies: BatchTallies,
    nowMs: number
): void {
    if (rules.length === 0 || records.length === 0) {
        return
    }
    for (const record of records) {
        // timestamp is Avro timestamp-micros; null means "no producer timestamp", which
        // ingestion treats as now — so it passes the staleness gate.
        if (record.timestamp != null && nowMs - record.timestamp / 1000 > MAX_RECORD_AGE_MS) {
            continue
        }
        for (const rule of rules) {
            let matches = true
            if (rule.filterGroup) {
                try {
                    matches = matchFilterGroup(rule.filterGroup, record)
                } catch {
                    tallies.evalErrors++
                    continue
                }
            }
            if (!matches) {
                continue
            }
            let value = 1
            if (rule.valueAttribute) {
                const parsed = resolveNumericValue(rule.valueAttribute, record)
                if (parsed == null) {
                    tallies.valueSkipped++
                    continue
                }
                value = parsed
            }

            const labelValues = rule.groupBy.map((key) => resolveLabelValue(key, record))
            const labelKey = JSON.stringify(labelValues)

            let ruleTallies = tallies.byRule.get(rule.id)
            if (!ruleTallies) {
                ruleTallies = new Map()
                tallies.byRule.set(rule.id, ruleTallies)
            }
            let entry = ruleTallies.get(labelKey)
            if (!entry) {
                if (ruleTallies.size >= MAX_LABEL_SETS_PER_RULE) {
                    tallies.seriesOverflow.set(rule.id, (tallies.seriesOverflow.get(rule.id) ?? 0) + 1)
                    continue
                }
                entry = { labelValues, count: 0, sum: 0, exemplarTraceId: null, exemplarSpanId: null }
                ruleTallies.set(labelKey, entry)
            }
            entry.count += 1
            entry.sum += value
            if (!entry.exemplarTraceId) {
                const traceIdHex = idToHex(record.trace_id, 16)
                if (traceIdHex) {
                    entry.exemplarTraceId = traceIdHex
                    entry.exemplarSpanId = idToHex(record.span_id, 8)
                }
            }
        }
    }
}
