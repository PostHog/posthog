import { compress, decompress } from '@mongodb-js/zstd'
import avro from 'avsc'
import { Histogram } from 'prom-client'
import { Readable } from 'stream'

import { instrumented } from '~/common/tracing/tracing-utils'

import type { LogsSettings } from '../types'
import { type LogBodyParseResult, parseLogBodyForIngestion } from './log-body-parse'
import { EMPTY_PII, type PiiScrubStats, scrubLogRecord } from './log-pii-scrub'

const MAX_JSON_ATTRIBUTES = 50

const SPAN_LOGS_DECODE = 'logsIngestionConsumer.handleEachBatch.decodeLogRecords'
const SPAN_LOGS_PARSE_BODIES = 'logsIngestionConsumer.handleEachBatch.parseLogBodies'
const SPAN_LOGS_ENRICH_JSON = 'logsIngestionConsumer.handleEachBatch.enrichJsonAttributes'
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

/**
 * Flattens a JSON object into a flat key-value map with dot-notation keys.
 * Arrays are indexed with numeric keys (e.g., "items.0.name").
 */
export function flattenJson(obj: unknown, prefix = '', result: Record<string, any> = {}): Record<string, any> {
    if (obj === null || obj === undefined) {
        if (prefix) {
            result[prefix] = String(obj)
        }
        return result
    }

    if (typeof obj !== 'object') {
        if (prefix) {
            result[prefix] = obj
        }
        return result
    }

    if (Array.isArray(obj)) {
        for (let i = 0; i < obj.length; i++) {
            flattenJson(obj[i], prefix ? `${prefix}.${i}` : String(i), result)
        }
        return result
    }

    for (const [key, value] of Object.entries(obj)) {
        const newKey = prefix ? `${prefix}.${key}` : key
        flattenJson(value, newKey, result)
    }

    return result
}

function jsonAttributesFromBodyParse(bodyParse: LogBodyParseResult): Record<string, string> {
    if (bodyParse.kind !== 'json_object_or_array') {
        return {}
    }

    const flattened = flattenJson(bodyParse.value)
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
    if (!record.body) {
        return record
    }

    const parse = bodyParse ?? parseLogBodyForIngestion(record.body)
    const existingAttributes = record.attributes || {}
    const jsonAttributes = jsonAttributesFromBodyParse(parse)

    if (Object.keys(jsonAttributes).length > 0) {
        record.attributes = {
            ...jsonAttributes,
            ...existingAttributes, // existing attributes take precedence
        }
    }

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
 * Processes an AVRO-encoded log message buffer containing multiple records.
 * Passthrough (no decode) when both json_parse_logs and pii_scrub_logs are off.
 * Otherwise: decode → optional PII scrub on `body` → optional parse bodies → optional JSON enrich → encode.
 *
 * When both `json_parse_logs` and `pii_scrub_logs` are on, scrub runs **before** parse/enrich so flattened JSON
 * attributes are derived from the redacted body string. `parseLogBodiesForIngestion` runs only when JSON parse is on.
 */
export const processLogMessageBuffer = instrumented({
    key: SPAN_LOGS_PROCESS_BUFFER,
    ...logRecordProcessInstrumentOpts,
})(async function processLogMessageBufferImpl(
    buffer: Buffer,
    settings: LogsSettings
): Promise<{ value: Buffer; pii: PiiScrubStats }> {
    const jsonParse = settings.json_parse_logs ?? false
    const piiScrub = settings.pii_scrub_logs ?? false

    if (!jsonParse && !piiScrub) {
        return { value: buffer, pii: EMPTY_PII }
    }

    const startTime = Date.now()
    let codec = 'unknown'

    try {
        const [logRecordType, compressionCodec, records] = await decodeLogRecordsInstrumented(buffer)
        codec = compressionCodec

        if (!logRecordType) {
            throw new Error('avro schema metadata not found')
        }

        let pii: PiiScrubStats = EMPTY_PII

        if (jsonParse && piiScrub) {
            pii = await scrubBatch(records)
            const bodyParses = await parseLogBodiesForIngestion(records)
            await enrichBatchJsonAttributes(records, bodyParses)
        } else if (jsonParse) {
            const bodyParses = await parseLogBodiesForIngestion(records)
            await enrichBatchJsonAttributes(records, bodyParses)
        } else if (piiScrub) {
            pii = await scrubBatch(records)
        }

        const value = await encodeLogRecordsInstrumented(logRecordType, codec, records)
        return { value, pii }
    } finally {
        const durationSeconds = (Date.now() - startTime) / 1000
        logProcessingDurationHistogram.observe(
            {
                json_parse_enabled: String(jsonParse),
                pii_scrub_enabled: String(piiScrub),
                compression_codec: codec,
            },
            durationSeconds
        )
    }
}) as (buffer: Buffer, settings: LogsSettings) => Promise<{ value: Buffer; pii: PiiScrubStats }>
