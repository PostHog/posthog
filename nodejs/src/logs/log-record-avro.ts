import { compress, decompress } from '@mongodb-js/zstd'
import avro from 'avsc'
import { Histogram } from 'prom-client'
import { Readable } from 'stream'

import { instrumented } from '~/common/tracing/tracing-utils'
import type { LogsSettings } from '~/types'

import { recordLogProcessingDuration } from './ingestion-otel-metrics'
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

const SPAN_LOGS_DECODE = 'logsIngestionConsumer.handleEachBatch.decodeLogRecords'
const SPAN_LOGS_PARSE_BODIES = 'logsIngestionConsumer.handleEachBatch.parseLogBodies'
const SPAN_LOGS_ENRICH_JSON = 'logsIngestionConsumer.handleEachBatch.enrichJsonAttributes'
const SPAN_LOGS_ENRICH_ATTRIBUTE_JSON = 'logsIngestionConsumer.handleEachBatch.enrichJsonAttributesFromAttribute'
const SPAN_LOGS_PII_SCRUB = 'logsIngestionConsumer.handleEachBatch.piiScrubLogRecords'
const SPAN_LOGS_ENCODE = 'logsIngestionConsumer.handleEachBatch.encodeLogRecords'
const SPAN_LOGS_PROCESS_BUFFER = 'logsIngestionConsumer.handleEachBatch.processLogMessageBuffer'

const logRecordProcessInstrumentOpts = { measureTime: false, sendException: false } as const

const logProcessingDurationHistogram = new Histogram({
    name: 'logs_ingestion_processing_duration_seconds',
    help: 'Time spent processing log messages (AVRO decode/encode cycle)',
    labelNames: ['json_parse_enabled', 'pii_scrub_enabled', 'compression_codec'],
    buckets: [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1],
})

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
        Promise.resolve(records.map((r) => parseLogBodyForIngestion(r.body)))
)

const encodeLogRecordsInstrumented = instrumented({
    key: SPAN_LOGS_ENCODE,
    ...logRecordProcessInstrumentOpts,
})(encodeLogRecords)

function* jsonEntries(value: object): Generator<[string, unknown]> {
    if (Array.isArray(value)) {
        for (let i = 0; i < value.length; i++) {
            yield [String(i), value[i]]
        }
    } else {
        for (const key in value) {
            if (Object.hasOwn(value, key)) {
                yield [key, (value as Record<string, unknown>)[key]]
            }
        }
    }
}

/**
 * Flattens a JSON object into a flat key-value map with dot-notation keys.
 * Arrays are indexed with numeric keys (e.g., "items.0.name").
 */
export function flattenJson(
    obj: unknown,
    prefix = '',
    result: Record<string, any> = {},
    maxAttributes = Infinity,
    maxBytes = MAX_LOG_RECORD_BYTES
): Record<string, any> | null {
    let bytes = 0
    for (const [key, value] of Object.entries(result)) {
        bytes += Buffer.byteLength(key) + Buffer.byteLength(JSON.stringify(value))
    }
    const prefixBytes = Buffer.byteLength(prefix)
    if (bytes > maxBytes || prefixBytes > maxBytes) {
        return null
    }
    if (obj === null || obj === undefined) {
        if (prefix) {
            return flattenJson({ [prefix]: String(obj) }, '', result, maxAttributes, maxBytes)
        }
        return result
    }

    if (typeof obj !== 'object') {
        if (prefix) {
            return flattenJson({ [prefix]: obj }, '', result, maxAttributes, maxBytes)
        }
        return result
    }

    // Retain path segments instead of full prefixes so deep objects cannot duplicate large keys on the stack.
    const path = prefix ? [prefix] : []
    const stack = [{ entries: jsonEntries(obj), pathLength: path.length, pathBytes: prefixBytes }]
    let count = Object.keys(result).length
    while (stack.length > 0 && count < maxAttributes) {
        const frame = stack[stack.length - 1]
        const next = frame.entries.next()
        if (next.done) {
            stack.pop()
            continue
        }
        const [key, value] = next.value
        const keyBytes = frame.pathBytes + (frame.pathBytes > 0 ? 1 : 0) + Buffer.byteLength(key)
        if (keyBytes > maxBytes) {
            return null
        }
        path.length = frame.pathLength
        if (keyBytes > 0) {
            path.push(key)
        }
        if (value !== null && typeof value === 'object') {
            stack.push({ entries: jsonEntries(value), pathLength: path.length, pathBytes: keyBytes })
        } else if (keyBytes > 0) {
            const normalized = value === null || value === undefined ? String(value) : value
            const valueBytes = Buffer.byteLength(JSON.stringify(normalized))
            const newKey = path.join('.')
            const exists = Object.hasOwn(result, newKey)
            const previousBytes = exists ? keyBytes + Buffer.byteLength(JSON.stringify(result[newKey])) : 0
            bytes += keyBytes + valueBytes - previousBytes
            if (bytes > maxBytes) {
                return null
            }
            if (!exists) {
                count++
            }
            result[newKey] = normalized
        }
    }

    return result
}

function jsonAttributesFromBodyParse(
    bodyParse: LogBodyParseResult,
    prefix = '',
    maxAttributes = MAX_JSON_ATTRIBUTES
): Record<string, string> {
    if (bodyParse.kind !== 'json_object_or_array') {
        return {}
    }

    const flattened = flattenJson(bodyParse.value, prefix, {}, maxAttributes)
    if (flattened === null) {
        return {}
    }
    const newAttributes: Record<string, string> = {}
    let count = 0

    for (const [key, value] of Object.entries(flattened)) {
        if (count >= MAX_JSON_ATTRIBUTES) {
            break
        }
        count++
        newAttributes[key] = JSON.stringify(value)
    }

    return newAttributes
}

function addJsonAttributes(
    record: LogRecord,
    jsonAttributes: Record<string, string>,
    preservedAttributes = record.attributes
): void {
    if (Object.keys(jsonAttributes).length === 0) {
        return
    }

    const attributes = {
        ...record.attributes,
        ...jsonAttributes,
        ...preservedAttributes, // sender-supplied attributes take precedence over both extraction sources
    }
    if (logRecordSizeBytes({ ...record, attributes }) <= MAX_LOG_RECORD_BYTES) {
        record.attributes = attributes
    }
}

/**
 * Parses the log body as JSON (if valid) and extracts flattened attributes.
 * Returns up to MAX_JSON_ATTRIBUTES attributes, without overwriting existing attributes.
 */
export function extractJsonAttributesFromBody(body: string | null): Record<string, string> {
    return jsonAttributesFromBodyParse(parseLogBodyForIngestion(body))
}

/**
 * Processes a LogRecord by parsing its body as JSON and adding flattened attributes.
 * Modifies the record in place and returns it.
 *
 * When `bodyParse` is omitted, parses once internally. When provided (e.g. from `processLogMessageBuffer`),
 * avoids a second parse of the same body string.
 */
export function enrichLogRecordWithJsonAttributes(record: LogRecord, bodyParse?: LogBodyParseResult): LogRecord {
    if (!record.body || logRecordSizeBytes(record) > MAX_LOG_RECORD_BYTES) {
        return record
    }

    const parse = bodyParse ?? parseLogBodyForIngestion(record.body)
    addJsonAttributes(record, jsonAttributesFromBodyParse(parse))

    return record
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

const enrichBatchAttributeJsonAttributes = instrumented({
    key: SPAN_LOGS_ENRICH_ATTRIBUTE_JSON,
    ...logRecordProcessInstrumentOpts,
})((records: LogRecord[], attributeKey: string, originalAttributes?: LogRecord['attributes'][]): Promise<void> => {
    for (const [index, record] of records.entries()) {
        const attribute = record.attributes?.[attributeKey]
        if (typeof attribute !== 'string' || logRecordSizeBytes(record) > MAX_LOG_RECORD_BYTES) {
            continue
        }
        let parsed = parseLogBodyForIngestion(attribute)
        if (parsed.kind === 'json_string') {
            // SDKs commonly stringify the attribute value, so the first parse yields the JSON document as a string.
            parsed = parseLogBodyForIngestion(parsed.value)
        }
        const jsonAttributes = jsonAttributesFromBodyParse(parsed, attributeKey, MAX_JSON_ATTRIBUTES)
        addJsonAttributes(record, jsonAttributes, originalAttributes ? originalAttributes[index] : record.attributes)
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
 * Scrubs before body and attribute extraction so flattened fields inherit redacted values.
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
    const attributeKey = settings.json_parse_logs_attribute_key
    // Body enrichment replaces the attribute map, so retain its scrubbed source to distinguish sender-supplied fields.
    const originalAttributes = jsonParse && attributeKey ? records.map((record) => record.attributes) : undefined
    if (jsonParse) {
        const bodyParses = await parseLogBodiesForIngestion(records)
        await enrichBatchJsonAttributes(records, bodyParses)
    }
    if (attributeKey) {
        await enrichBatchAttributeJsonAttributes(records, attributeKey, originalAttributes)
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
        !!settings.json_parse_logs_attribute_key
    if (normalizeActive || stageCount > 0) {
        return 'decode_and_reencode'
    }
    return hasVisitor ? 'decode_only' : 'passthrough'
}

/**
 * The single decode → transform → encode path for a log message buffer.
 * Passthrough (no decode) when body parsing, attribute parsing, and PII scrubbing are off,
 * there are no `stages`, and no `onRecordsDecoded` visitor.
 * Otherwise: decode → normalize (optional PII scrub, then body and attribute extraction) →
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
