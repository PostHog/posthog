import { compress, decompress } from '@mongodb-js/zstd'
import avro from 'avsc'
import { Counter, Histogram } from 'prom-client'
import { Readable } from 'stream'

import { instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import type { LogsSettings } from '~/types'

import { recordJsonEnrichmentSkipped, recordLogProcessingDuration } from './ingestion-otel-metrics'
import { type LogBodyParseResult, parseLogBodyForIngestion } from './log-body-parse'
import { EMPTY_PII, type PiiScrubStats, scrubLogRecord } from './log-pii-scrub'
import { MAX_LOG_RECORD_BYTES, logRecordSizeBytes } from './log-record-size'
import {
    type DropStats,
    EMPTY_DROP_STATS,
    type PipelineStage,
    runPipelineStages,
} from './pipeline/log-processing-pipeline'

const MAX_JSON_ATTRIBUTES = 50
const MAX_JSON_NODES = 10_000
const MAX_JSON_DEPTH = 128

const SPAN_LOGS_DECODE = 'logsIngestionConsumer.handleEachBatch.decodeLogRecords'
const SPAN_LOGS_PARSE_BODIES = 'logsIngestionConsumer.handleEachBatch.parseLogBodies'
const SPAN_LOGS_ENRICH_JSON = 'logsIngestionConsumer.handleEachBatch.enrichJsonAttributes'
const SPAN_LOGS_PII_SCRUB = 'logsIngestionConsumer.handleEachBatch.piiScrubLogRecords'
const SPAN_LOGS_ENCODE = 'logsIngestionConsumer.handleEachBatch.encodeLogRecords'
const SPAN_LOGS_PROCESS_BUFFER = 'logsIngestionConsumer.handleEachBatch.processLogMessageBuffer'

const logRecordProcessInstrumentOpts = { measureTime: false, sendException: false } as const

export const logProcessingDurationHistogram = new Histogram({
    name: 'logs_ingestion_processing_duration_seconds',
    help: 'Time spent processing log messages (AVRO decode/encode cycle)',
    labelNames: ['json_parse_enabled', 'pii_scrub_enabled', 'attribute_extraction_enabled', 'compression_codec'],
    buckets: [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1],
})

export const logsJsonAttributeSniffCounter = new Counter({
    name: 'logs_ingestion_json_attribute_sniff_total',
    help: 'Log records inspected for a configured JSON attribute prefix, without parsing or extracting fields',
    labelNames: ['team_id', 'outcome'],
})

export const logsJsonEnrichmentSkippedCounter = new Counter({
    name: 'logs_ingestion_json_enrichment_skipped_total',
    help: 'Log JSON enrichment skipped because a size or traversal budget was exceeded',
    labelNames: ['reason', 'source'],
})

/** Which enrichment path hit the budget: the log body, or the configured JSON attribute. */
type JsonEnrichmentSource = 'body' | 'selected_attribute'

function recordJsonEnrichmentSkip(
    reason: 'input_size' | 'flatten_budget' | 'output_size',
    source: JsonEnrichmentSource
): void {
    logsJsonEnrichmentSkippedCounter.inc({ reason, source })
    recordJsonEnrichmentSkipped(reason, source)
}

export function sniffJsonLogAttributes(
    records: readonly Pick<LogRecord, 'attributes'>[],
    attributeKey: string,
    teamId: number
): void {
    for (const record of records) {
        let outcome: 'missing_key' | 'looks_like_json' | 'other' = 'missing_key'
        if (record.attributes && Object.hasOwn(record.attributes, attributeKey)) {
            const value = record.attributes[attributeKey]
            outcome = /^[ \t\r\n]*"?(?:[ \t\r\n]|\\[nrt])*[{\[]/.test(value.slice(0, 64)) ? 'looks_like_json' : 'other'
        }
        logsJsonAttributeSniffCounter.inc({ team_id: String(teamId), outcome })
    }
}

export interface LogRecord {
    uuid: string | null
    trace_id: Buffer | null
    span_id: Buffer | null
    trace_flags: number | null
    timestamp: number | null
    observed_timestamp: number | null
    body: string | null
    severity_text: string | null
    severity_number: number | null
    service_name: string | null
    resource_attributes: Record<string, string> | null
    instrumentation_scope: string | null
    event_name: string | null
    attributes: Record<string, string> | null
    bytes_uncompressed?: number | null
    /** Per-row retention in days, stamped by the retention stage from team retention rules. Null/undefined
     * leaves ClickHouse to fall back to the batch `retention-days` header (the team default). */
    retention_days?: number | null
    /** Masked body, stamped by the pattern masking stage. Identifiers become placeholders, so two
     * lines differing only by a request id share one pattern. */
    pattern?: string | null
    /** Masking rule set that produced `pattern`. Null reads as 0 in ClickHouse, marking a row
     * written before masking. */
    pattern_version?: number | null
}

export async function decodeLogRecords(buffer: Buffer): Promise<[avro.Type | undefined, string, LogRecord[]]> {
    return new Promise((resolve, reject) => {
        try {
            const records: LogRecord[] = []

            const decoder = new avro.streams.BlockDecoder({
                codecs: {
                    zstandard: (buf: Buffer, cb: (err: Error | null, inflated?: Buffer) => void) => {
                        decompress(buf)
                            .then((inflated) => cb(null, inflated))
                            .catch(cb)
                    },
                },
            })

            const stream = new Readable()
            stream.on('error', (err: Error) => {
                reject(err)
            })
            stream.push(buffer)
            stream.push(null)
            stream.pipe(decoder)

            let logRecordType: avro.Type | undefined
            let compressionCodec: string = 'null'

            // pull the schema out from the metadata
            decoder.on('metadata', (type: avro.types.RecordType, codec?: string) => {
                logRecordType = type
                compressionCodec = codec || 'null'
            })

            decoder.on('data', (record: unknown) => {
                records.push(record as LogRecord)
            })

            decoder.on('end', () => {
                if (logRecordType === undefined) {
                    reject(new Error('No metadata found'))
                    return
                }
                resolve([logRecordType, compressionCodec, records])
            })

            decoder.on('error', (err: Error) => {
                reject(err)
            })
        } catch (err) {
            reject(err)
        }
    })
}

const decodeLogRecordsInstrumented = instrumented({
    key: SPAN_LOGS_DECODE,
    ...logRecordProcessInstrumentOpts,
})(decodeLogRecords)

export async function encodeLogRecords(logRecordType: avro.Type, codec: string, records: LogRecord[]): Promise<Buffer> {
    return new Promise((resolve, reject) => {
        try {
            const buffers: Buffer[] = []

            const encoder = new avro.streams.BlockEncoder(logRecordType, {
                codec: codec,
                codecs: {
                    zstandard: (buf: Buffer, cb: (err: Error | null, compressed?: Buffer) => void) => {
                        compress(buf, 1)
                            .then((compressed) => cb(null, compressed))
                            .catch(cb)
                    },
                },
            })

            encoder.on('error', (err: Error) => {
                reject(err)
            })

            encoder.on('data', (buf: Buffer) => {
                buffers.push(buf)
            })

            encoder.on('end', () => {
                resolve(Buffer.concat(buffers))
            })

            for (const record of records) {
                encoder.write(record)
            }

            encoder.end()
        } catch (err) {
            reject(err)
        }
    })
}

const parseLogBodiesForIngestion = instrumented({
    key: SPAN_LOGS_PARSE_BODIES,
    ...logRecordProcessInstrumentOpts,
})(
    (records: LogRecord[]): Promise<LogBodyParseResult[]> =>
        Promise.resolve(
            records.map((record) =>
                parseLogBodyForIngestion(
                    record.body && Buffer.byteLength(record.body) > MAX_LOG_RECORD_BYTES ? null : record.body
                )
            )
        )
)

const encodeLogRecordsInstrumented = instrumented({
    key: SPAN_LOGS_ENCODE,
    ...logRecordProcessInstrumentOpts,
})(encodeLogRecords)

function isArrayIndex(key: string): boolean {
    const index = Number(key)
    return Number.isInteger(index) && index >= 0 && index < 2 ** 32 - 1 && String(index) === key
}

function countJsonNodesWithinBudget(value: unknown, depth: number, budget: number): number | null {
    const stack = [{ value, depth }]
    let nodes = 1
    while (stack.length > 0) {
        const entry = stack.pop()!
        if (nodes > budget || entry.depth > MAX_JSON_DEPTH) {
            return null
        }
        if (entry.value !== null && typeof entry.value === 'object') {
            for (const key in entry.value) {
                if (!Object.hasOwn(entry.value, key)) {
                    continue
                }
                if (++nodes > budget) {
                    return null
                }
                stack.push({ value: (entry.value as Record<string, unknown>)[key], depth: entry.depth + 1 })
            }
        }
    }
    return nodes
}

/**
 * Flattens a JSON object into a flat key-value map with dot-notation keys.
 * Body arrays use indexed paths; selected-attribute arrays are stored as JSON strings.
 */
function flattenJsonWithBudget(
    obj: unknown,
    prefix = '',
    maxAttributes = MAX_JSON_ATTRIBUTES,
    maxBytes = MAX_LOG_RECORD_BYTES,
    arrayMode: 'indexed' | 'string' = 'indexed'
): { values: Record<string, unknown>; attributes: Record<string, string> } | null {
    const result: Record<string, unknown> = {}
    const attributes: Record<string, string> = {}
    const stack = [{ value: obj, prefix, depth: 0 }]
    let nodes = 1
    let pathBytes = Buffer.byteLength(prefix)
    let attributeBytes = 0
    let attributeCount = 0
    let lastRetainedKey = ''

    while (stack.length > 0) {
        const entry = stack.pop()!
        if (entry.depth > MAX_JSON_DEPTH || pathBytes > maxBytes) {
            return null
        }
        if (arrayMode === 'string' && Array.isArray(entry.value)) {
            const arrayNodes = countJsonNodesWithinBudget(entry.value, entry.depth, MAX_JSON_NODES - nodes + 1)
            if (arrayNodes === null) {
                return null
            }
            nodes += arrayNodes - 1
            entry.value = JSON.stringify(entry.value)
        }
        if (entry.value !== null && typeof entry.value === 'object') {
            const value = entry.value as Record<string, unknown>
            if (Array.isArray(value) && value.length + nodes > MAX_JSON_NODES) {
                return null
            }
            const keys = Array.isArray(value) ? Array.from({ length: value.length }, (_, index) => String(index)) : []
            if (!Array.isArray(value)) {
                for (const key in value) {
                    if (!Object.hasOwn(value, key)) {
                        continue
                    }
                    if (nodes + keys.length >= MAX_JSON_NODES) {
                        return null
                    }
                    keys.push(key)
                }
            }
            nodes += keys.length
            for (let index = keys.length - 1; index >= 0; index--) {
                const key = keys[index]
                const childPrefix = entry.prefix ? `${entry.prefix}.${key}` : key
                pathBytes += Buffer.byteLength(childPrefix)
                if (pathBytes > maxBytes) {
                    return null
                }
                stack.push({ value: value[key], prefix: childPrefix, depth: entry.depth + 1 })
            }
            continue
        }

        const key = entry.prefix
        if (!key || key === '__proto__' || maxAttributes <= 0) {
            continue
        }
        const exists = Object.hasOwn(result, key)
        if (!exists && attributeCount >= maxAttributes) {
            if (!isArrayIndex(key)) {
                continue
            }
            const lastKey = lastRetainedKey
            if (isArrayIndex(lastKey) && Number(lastKey) <= Number(key)) {
                continue
            }
            attributeBytes -= Buffer.byteLength(lastKey) + Buffer.byteLength(attributes[lastKey])
            delete result[lastKey]
            delete attributes[lastKey]
            attributeCount--
        }
        const value = entry.value === null || entry.value === undefined ? String(entry.value) : entry.value
        const serialized = JSON.stringify(value)
        const valueBytes = Buffer.byteLength(serialized)
        attributeBytes += exists ? valueBytes - Buffer.byteLength(attributes[key]) : Buffer.byteLength(key) + valueBytes
        if (attributeBytes > maxBytes) {
            return null
        }
        result[key] = value
        attributes[key] = serialized
        if (!exists) {
            attributeCount++
            if (attributeCount === maxAttributes) {
                lastRetainedKey = Object.keys(result)[attributeCount - 1]
            }
        }
    }
    return { values: result, attributes }
}

export function flattenJson(
    obj: unknown,
    prefix = '',
    maxAttributes = MAX_JSON_ATTRIBUTES,
    maxBytes = MAX_LOG_RECORD_BYTES
): Record<string, unknown> | null {
    return flattenJsonWithBudget(obj, prefix, maxAttributes, maxBytes)?.values ?? null
}

function jsonAttributesFromBodyParse(bodyParse: LogBodyParseResult): Record<string, string> {
    if (bodyParse.kind !== 'json_object_or_array') {
        return {}
    }

    const flattened = flattenJsonWithBudget(bodyParse.value)
    if (flattened === null) {
        recordJsonEnrichmentSkip('flatten_budget', 'body')
        return {}
    }
    return flattened.attributes
}

/**
 * Parses the log body as JSON (if valid) and extracts flattened attributes.
 * Returns up to MAX_JSON_ATTRIBUTES attributes, without overwriting existing attributes.
 */
export function extractJsonAttributesFromBody(body: string | null): Record<string, string> {
    if (body && Buffer.byteLength(body) > MAX_LOG_RECORD_BYTES) {
        recordJsonEnrichmentSkip('input_size', 'body')
        return {}
    }
    return jsonAttributesFromBodyParse(parseLogBodyForIngestion(body))
}

function addJsonAttributes(
    record: LogRecord,
    jsonAttributes: Record<string, string>,
    recordBytes: number,
    source: JsonEnrichmentSource
): void {
    if (Object.keys(jsonAttributes).length === 0) {
        return
    }
    for (const [key, value] of Object.entries(jsonAttributes)) {
        if (!record.attributes || !Object.hasOwn(record.attributes, key)) {
            recordBytes += Buffer.byteLength(key) + Buffer.byteLength(value)
            if (recordBytes > MAX_LOG_RECORD_BYTES) {
                recordJsonEnrichmentSkip('output_size', source)
                return
            }
        }
    }
    record.attributes = {
        ...jsonAttributes,
        ...record.attributes, // existing attributes take precedence
    }
}

/**
 * Processes a LogRecord by parsing its body as JSON and adding flattened attributes.
 * Modifies the record in place and returns it.
 *
 * When `bodyParse` is omitted, parses once internally. When provided (e.g. from `processLogMessageBuffer`),
 * avoids a second parse of the same body string.
 */
export function enrichLogRecordWithJsonAttributes(record: LogRecord, bodyParse?: LogBodyParseResult): LogRecord {
    if (!record.body) {
        return record
    }

    if (Buffer.byteLength(record.body) > MAX_LOG_RECORD_BYTES) {
        recordJsonEnrichmentSkip('input_size', 'body')
        return record
    }

    const parse = bodyParse ?? parseLogBodyForIngestion(record.body)
    if (parse.kind !== 'json_object_or_array') {
        return record
    }
    const recordBytes = logRecordSizeBytes(record)
    if (recordBytes > MAX_LOG_RECORD_BYTES) {
        recordJsonEnrichmentSkip('input_size', 'body')
        return record
    }
    const jsonAttributes = jsonAttributesFromBodyParse(parse)
    addJsonAttributes(record, jsonAttributes, recordBytes, 'body')

    return record
}

export function enrichLogRecordFromJsonAttribute(record: LogRecord, key: string): void {
    if (!record.attributes || !Object.hasOwn(record.attributes, key)) {
        return
    }
    const recordBytes = logRecordSizeBytes(record)
    if (recordBytes > MAX_LOG_RECORD_BYTES) {
        recordJsonEnrichmentSkip('input_size', 'selected_attribute')
        return
    }
    let parsed: unknown
    try {
        parsed = parseJSON(record.attributes[key])
        if (typeof parsed === 'string') {
            parsed = parseJSON(parsed)
        }
    } catch {
        return
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return
    }
    const flattened = flattenJsonWithBudget(parsed, key, MAX_JSON_ATTRIBUTES, MAX_LOG_RECORD_BYTES, 'string')
    if (flattened === null) {
        recordJsonEnrichmentSkip('flatten_budget', 'selected_attribute')
        return
    }
    addJsonAttributes(record, flattened.attributes, recordBytes, 'selected_attribute')
}

const enrichBatchJsonAttributes = instrumented({
    key: SPAN_LOGS_ENRICH_JSON,
    ...logRecordProcessInstrumentOpts,
})((records: LogRecord[], bodyParses: LogBodyParseResult[]): Promise<void> => {
    for (let i = 0; i < records.length; i++) {
        enrichLogRecordWithJsonAttributes(records[i], bodyParses[i])
    }
    return Promise.resolve()
})

const scrubBatch = instrumented({
    key: SPAN_LOGS_PII_SCRUB,
    ...logRecordProcessInstrumentOpts,
})((records: LogRecord[]): Promise<PiiScrubStats> => {
    let piiReplacements = 0
    for (const record of records) {
        piiReplacements += scrubLogRecord(record).piiReplacements
    }
    return Promise.resolve({ piiReplacements })
})

/**
 * Scrub before extracting fields, then enrich from the selected attribute before the body so
 * sender attributes win over selected-attribute fields, which win over body-derived fields.
 */
export async function transformDecodedLogRecordsInPlace(
    records: LogRecord[],
    settings: LogsSettings
): Promise<PiiScrubStats> {
    const jsonParse = settings.json_parse_logs ?? false
    const piiScrub = settings.pii_scrub_logs ?? false
    let pii: PiiScrubStats = EMPTY_PII
    if (piiScrub) {
        pii = await scrubBatch(records)
    }
    if (settings.json_parse_logs_attribute_key) {
        for (const record of records) {
            enrichLogRecordFromJsonAttribute(record, settings.json_parse_logs_attribute_key)
        }
    }
    if (jsonParse) {
        const bodyParses = await parseLogBodiesForIngestion(records)
        await enrichBatchJsonAttributes(records, bodyParses)
    }
    return pii
}

/** Applied to decoded records after the built-in transforms; mutates the array in place
 * (dropped records are removed). Used to run hog log transformations last. */
export type LogRecordsTransform = (records: LogRecord[]) => Promise<unknown>

export type ProcessLogMessageBufferOptions = {
    /** Runs after normalize and before the stages — sees every record post-scrub and pre-drop. */
    onRecordsDecoded?: (records: LogRecord[]) => void
    /** Ordered mutate/filter stages (sampling, hog transforms, per-row retention). */
    stages?: PipelineStage[]
}

export type ProcessLogMessageBufferResult = {
    value: Buffer | null
    pii: PiiScrubStats
    drops: DropStats
}

/**
 * How much work `processLogMessageBuffer` does with a buffer, cheapest first: `passthrough` forwards
 * it untouched, `decode_only` decodes for a visitor then forwards the original, `decode_and_reencode`
 * decodes, transforms and encodes again.
 */
export type BufferProcessingMode = 'passthrough' | 'decode_only' | 'decode_and_reencode'

/**
 * Give the buffer's current stage count, not the count it would have. A tier below
 * `decode_and_reencode` names the work one more stage adds: `decode_only` adds an encode,
 * `passthrough` adds a decode and an encode.
 */
export function bufferProcessingMode(
    settings: LogsSettings,
    stageCount: number,
    hasVisitor: boolean
): BufferProcessingMode {
    const normalizeActive =
        (settings.json_parse_logs ?? false) ||
        (settings.pii_scrub_logs ?? false) ||
        Boolean(settings.json_parse_logs_attribute_key)
    if (normalizeActive || stageCount > 0) {
        return 'decode_and_reencode'
    }
    return hasVisitor ? 'decode_only' : 'passthrough'
}

/**
 * The single decode → transform → encode path for a log message buffer.
 * Passthrough (no decode) when body parsing, attribute extraction and PII scrubbing are off,
 * there are no `stages`, and no `onRecordsDecoded` visitor.
 * Otherwise: decode → normalize (PII scrub, selected-attribute extraction, body enrichment) →
 * `onRecordsDecoded` visitor → run `stages` in order → encode.
 *
 * When both `json_parse_logs` and `pii_scrub_logs` are on, scrub runs **before** parse/enrich so flattened JSON
 * attributes are derived from the redacted body string. A read-only message (no normalize, no stages)
 * that only ran a visitor is returned untouched — no re-encode.
 *
 * `value` is null when the stages dropped every record — the caller must not produce it downstream.
 */
export const processLogMessageBuffer = instrumented({
    key: SPAN_LOGS_PROCESS_BUFFER,
    ...logRecordProcessInstrumentOpts,
})(async function processLogMessageBufferImpl(
    buffer: Buffer,
    settings: LogsSettings,
    options: ProcessLogMessageBufferOptions = {}
): Promise<ProcessLogMessageBufferResult> {
    const { onRecordsDecoded, stages = [] } = options
    const processingMode = bufferProcessingMode(settings, stages.length, Boolean(onRecordsDecoded))

    if (processingMode === 'passthrough') {
        // Passthrough: nothing mutates or drops and no visitor needs the records — forward untouched.
        return { value: buffer, pii: EMPTY_PII, drops: EMPTY_DROP_STATS() }
    }

    // Read only by the duration labels in the `finally`, which the passthrough return never reaches.
    const jsonParse = settings.json_parse_logs ?? false
    const piiScrub = settings.pii_scrub_logs ?? false
    const attributeExtraction = Boolean(settings.json_parse_logs_attribute_key)
    const startTime = Date.now()
    let codec = 'unknown'

    try {
        const [logRecordType, compressionCodec, records] = await decodeLogRecordsInstrumented(buffer)
        codec = compressionCodec

        if (!logRecordType) {
            throw new Error('avro schema metadata not found')
        }

        const pii = await transformDecodedLogRecordsInPlace(records, settings)
        onRecordsDecoded?.(records)

        const { kept, stats } = await runPipelineStages(records, stages)

        if (kept.length === 0) {
            // No surviving records — signal the caller to suppress the message rather than forward or
            // re-encode an empty batch downstream. Checked before the visitor-only shortcut below so a
            // zero-record batch decoded solely for metric-rule tallying is suppressed too.
            // `stats.droppedBy` distinguishes a filter drop (sampling / transformations) from an
            // already-empty batch so the caller can attribute it correctly.
            return { value: null, pii, drops: stats }
        }
        if (processingMode === 'decode_only') {
            // Only a visitor ran and records survive — the buffer is unchanged, so forward it without
            // re-encoding.
            return { value: buffer, pii, drops: stats }
        }

        const value = await encodeLogRecordsInstrumented(logRecordType, codec, kept)
        return { value, pii, drops: stats }
    } finally {
        const durationSeconds = (Date.now() - startTime) / 1000
        const durationLabels = {
            json_parse_enabled: String(jsonParse),
            pii_scrub_enabled: String(piiScrub),
            attribute_extraction_enabled: String(attributeExtraction),
            compression_codec: codec,
        }
        logProcessingDurationHistogram.observe(durationLabels, durationSeconds)
        recordLogProcessingDuration(durationSeconds, durationLabels)
    }
}) as (
    buffer: Buffer,
    settings: LogsSettings,
    options?: ProcessLogMessageBufferOptions
) => Promise<ProcessLogMessageBufferResult>
