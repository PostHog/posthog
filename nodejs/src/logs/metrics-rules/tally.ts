import { createHmac, randomBytes } from 'crypto'

import { decodeLogAttributeValue } from '../attribute-value'
import type { LogRecord } from '../log-record-avro'
import { matchFilterGroup } from '../sampling/filter-group-match'
import type { CompiledMetricRule } from './compile-metric-rules'

/** Cap on distinct group-by label sets per rule per batch — bounds emitted series cardinality. */
export const MAX_LABEL_SETS_PER_RULE = 1000

/** Not valid JSON, so no real label set (always a JSON array) can collide with it. */
export const OVERFLOW_LABEL_KEY = '__overflow__'

/** The OTel SDK default explicit bucket bounds, so percentiles match an SDK-sent histogram. */
export const DEFAULT_HISTOGRAM_BOUNDS: readonly number[] = [
    0, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000,
]

export const MAX_LABEL_VALUE_LENGTH = 256

/**
 * Records with timestamps older than this never feed a metric, so a backfill of
 * historical logs cannot distort the "now" data point (matches Datadog's 20-minute
 * aggregation window for log-based metrics).
 */
export const MAX_RECORD_AGE_MS = 20 * 60 * 1000

/** OTel span status codes (`StatusCode` in the span Avro schema). Anything outside
 * this map falls back to the raw numeric string so an unknown future code still
 * emits a distinguishable label. */
export const SPAN_STATUS_CODE_LABELS: Record<number, string> = { 0: 'UNSET', 1: 'OK', 2: 'ERROR' }

/** OTel span kinds (`SpanKind` in the span Avro schema), 1-based per the spec. */
export const SPAN_KIND_LABELS: Record<number, string> = {
    1: 'INTERNAL',
    2: 'SERVER',
    3: 'CLIENT',
    4: 'PRODUCER',
    5: 'CONSUMER',
}

export type MetricTallyEntry = {
    /** Group-by values in the rule's `groupBy` key order. */
    labelValues: string[]
    count: number
    sum: number
    bucketCounts: number[] | null
    overflow: boolean
    exemplarTraceId: string | null
    exemplarSpanId: string | null
}

export type BatchTallies = {
    byRule: Map<string, Map<string, MetricTallyEntry>>
    /** Records that matched after the rule hit its label-set cap, tallied into the overflow series. */
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

/**
 * Pseudo value-attribute key resolving to the span's wall-clock duration in
 * milliseconds, computed from `end_time - timestamp`. Lets a span rule emit a
 * latency distribution without any SDK attribute convention. Meaningful only
 * for `source === 'spans'` rules.
 */
export const SPAN_VALUE_DURATION_MS = 'duration_ms'

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
    // Span top-level keys. A span arrives as a LogRecord through the shared Avro
    // decode path, carrying these extra fields (absent on log records).
    if (key === 'name') {
        return (record as { name?: string | null }).name
    }
    if (key === 'status_code') {
        // Emit the OTel enum name as the series label (`ERROR`, not `2`) so dashboards
        // and alerts read without knowing the wire encoding. Filter matching keeps the
        // numeric form — see filter-group-match.ts, where users write `value: '2'`.
        const code = (record as { status_code?: number | null }).status_code
        return code == null ? undefined : (SPAN_STATUS_CODE_LABELS[code] ?? String(code))
    }
    if (key === 'kind') {
        // Same enum-label treatment as status_code: `SERVER`, not `2`.
        const kind = (record as { kind?: number | null }).kind
        return kind == null ? undefined : (SPAN_KIND_LABELS[kind] ?? String(kind))
    }
    if (key.startsWith(ATTRIBUTES_PREFIX)) {
        return decodedAttr(record.attributes, key.slice(ATTRIBUTES_PREFIX.length))
    }
    if (key.startsWith(RESOURCE_ATTRIBUTES_PREFIX)) {
        return decodedAttr(record.resource_attributes, key.slice(RESOURCE_ATTRIBUTES_PREFIX.length))
    }
    return undefined
}

/**
 * Attribute map values are JSON-encoded on the Avro wire (a string arrives as
 * `"pod-1"`, quotes included). Decode at the read so labels match what the Logs
 * UI shows and numeric value attributes parse instead of tallying as NaN.
 */
function decodedAttr(map: Record<string, string> | null | undefined, key: string): string | undefined {
    const raw = map?.[key]
    return raw === undefined ? undefined : decodeLogAttributeValue(raw)
}

function resolveLabelValue(key: string, record: LogRecord): string {
    const value = lookupKey(key, record) ?? ''
    return value.length > MAX_LABEL_VALUE_LENGTH ? value.slice(0, MAX_LABEL_VALUE_LENGTH) : value
}

const SERIES_WINDOW_MS = 60 * 60 * 1000

export const MAX_ADMITTED_LABEL_SETS_PER_TEAM = 5_000
export const MAX_ADMITTED_LABEL_SETS = 500_000

/**
 * HMAC with a random per-process key, truncated to 48 bits. A team cannot craft colliding labels
 * offline, so a collision cannot admit extra label sets past the cap.
 */
const LABEL_HASH_KEY = randomBytes(32)

function hashLabelKey(labelKey: string): number {
    return createHmac('sha256', LABEL_HASH_KEY).update(labelKey).digest().readUIntBE(0, 6)
}

/**
 * Bounds the label sets each rule admits per hour in this process. Batch tallies start empty,
 * so without this a rule whose labels change every batch would store new series without limit.
 * The window matches the hourly series grain of metric samples.
 */
export class MetricSeriesAdmission {
    private window = -1
    private admitted = new Map<string, Set<number>>()
    // Counts survive rule deletion until the hour changes, so rule churn cannot reset a team's budget.
    private admittedByTeam = new Map<number, number>()
    private admittedTotal = 0

    constructor(
        private readonly maxPerRule: number = MAX_LABEL_SETS_PER_RULE,
        private readonly maxPerTeam: number = MAX_ADMITTED_LABEL_SETS_PER_TEAM,
        private readonly maxTotal: number = MAX_ADMITTED_LABEL_SETS
    ) {}

    public admit(teamId: number, ruleId: string, labelKey: string, nowMs: number): boolean {
        const window = Math.floor(nowMs / SERIES_WINDOW_MS)
        if (window !== this.window) {
            this.admitted.clear()
            this.admittedByTeam.clear()
            this.admittedTotal = 0
            this.window = window
        }
        const key = `${teamId}:${ruleId}`
        const labelHash = hashLabelKey(labelKey)
        let labelHashes = this.admitted.get(key)
        if (labelHashes?.has(labelHash)) {
            return true
        }
        const teamAdmitted = this.admittedByTeam.get(teamId) ?? 0
        if (
            (labelHashes?.size ?? 0) >= this.maxPerRule ||
            teamAdmitted >= this.maxPerTeam ||
            this.admittedTotal >= this.maxTotal
        ) {
            return false
        }
        if (!labelHashes) {
            labelHashes = new Set()
            this.admitted.set(key, labelHashes)
        }
        labelHashes.add(labelHash)
        this.admittedByTeam.set(teamId, teamAdmitted + 1)
        this.admittedTotal++
        return true
    }
}

function histogramBucketIndex(value: number): number {
    for (let i = 0; i < DEFAULT_HISTOGRAM_BOUNDS.length; i++) {
        if (value <= DEFAULT_HISTOGRAM_BOUNDS[i]!) {
            return i
        }
    }
    return DEFAULT_HISTOGRAM_BOUNDS.length
}

function newTallyEntry(labelValues: string[], withBuckets: boolean, overflow: boolean): MetricTallyEntry {
    return {
        labelValues,
        count: 0,
        sum: 0,
        bucketCounts: withBuckets ? new Array<number>(DEFAULT_HISTOGRAM_BOUNDS.length + 1).fill(0) : null,
        overflow,
        exemplarTraceId: null,
        exemplarSpanId: null,
    }
}

function resolveNumericValue(key: string, record: LogRecord): number | null {
    // Span wall-clock duration from Avro timestamp-micros, no attribute lookup.
    if (key === SPAN_VALUE_DURATION_MS) {
        const r = record as { timestamp?: number | null; end_time?: number | null }
        if (r.timestamp == null || r.end_time == null) {
            return null
        }
        const durationMs = (r.end_time - r.timestamp) / 1000
        return Number.isFinite(durationMs) && durationMs >= 0 ? durationMs : null
    }
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
export function idToHex(buffer: Buffer | null, expectedBytes: number): string | null {
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
    nowMs: number,
    admitLabelSet?: (ruleId: string, labelKey: string) => boolean
): void {
    if (rules.length === 0 || records.length === 0) {
        return
    }
    for (const record of records) {
        // For a span, `timestamp` is the START time and the record is not exported until
        // the span ends — so gating on `timestamp` would measure span duration + export
        // lag, not staleness, and silently drop long-running spans (truncating exactly
        // the latency tail a duration_ms rule exists to show). Gate on `end_time` when
        // present, falling back to `timestamp` for logs and spans without an end.
        // Both are Avro timestamp-micros; null means "no producer timestamp", which
        // ingestion treats as now — so it passes the staleness gate.
        const observedAtMicros = (record as { end_time?: number | null }).end_time ?? record.timestamp
        if (observedAtMicros != null && nowMs - observedAtMicros / 1000 > MAX_RECORD_AGE_MS) {
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
            let labelKey = JSON.stringify(labelValues)

            let ruleTallies = tallies.byRule.get(rule.id)
            if (!ruleTallies) {
                ruleTallies = new Map()
                tallies.byRule.set(rule.id, ruleTallies)
            }
            let entry = ruleTallies.get(labelKey)
            if (!entry) {
                const overflowEntry = ruleTallies.get(OVERFLOW_LABEL_KEY)
                const realLabelSets = ruleTallies.size - (overflowEntry ? 1 : 0)
                const admitted = realLabelSets < MAX_LABEL_SETS_PER_RULE && (admitLabelSet?.(rule.id, labelKey) ?? true)
                if (!admitted) {
                    // Past the cap the record still counts, on one shared series, so rule totals stay correct.
                    tallies.seriesOverflow.set(rule.id, (tallies.seriesOverflow.get(rule.id) ?? 0) + 1)
                    labelKey = OVERFLOW_LABEL_KEY
                    entry = overflowEntry
                    if (!entry) {
                        entry = newTallyEntry(
                            rule.groupBy.map(() => ''),
                            rule.valueAttribute !== null,
                            true
                        )
                        ruleTallies.set(labelKey, entry)
                    }
                } else {
                    entry = newTallyEntry(labelValues, rule.valueAttribute !== null, false)
                    ruleTallies.set(labelKey, entry)
                }
            }
            entry.count += 1
            entry.sum += value
            if (entry.bucketCounts) {
                entry.bucketCounts[histogramBucketIndex(value)]! += 1
            }
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
