import { compress, decompress } from '@mongodb-js/zstd'
import avro from 'avsc'

import { parseJSON } from '../utils/json-parse'

const MAX_JSON_ATTRIBUTES = 50

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

export async function decodeLogRecords(buffer: Buffer): Promise<[avro.Type | undefined, LogRecord[]]> {
    return new Promise((resolve, reject) => {
        try {
            const records: LogRecord[] = []
            const { Readable } = require('stream')

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
            stream.push(buffer)
            stream.push(null)
            stream.pipe(decoder)

            let logRecordType: avro.Type | undefined

            // pull the schema out from the metadata
            decoder.on('metadata', (type: avro.types.RecordType) => {
                logRecordType = type
            })

            decoder.on('data', (record: unknown) => {
                records.push(record as LogRecord)
            })

            decoder.on('end', () => {
                if (logRecordType === undefined) {
                    reject(new Error('No metadata found'))
                    return
                }
                resolve([logRecordType, records])
            })

            decoder.on('error', (err: Error) => {
                reject(err)
            })
        } catch (err) {
            reject(err)
        }
    })
}

export async function encodeLogRecords(logRecordType: avro.Type, records: LogRecord[]): Promise<Buffer> {
    return new Promise((resolve, reject) => {
        try {
            const buffers: Buffer[] = []

            const encoder = new avro.streams.BlockEncoder(logRecordType, {
                codec: 'zstandard',
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

/**
 * Flattens a JSON object into a flat key-value map with dot-notation keys.
 * Arrays are indexed with numeric keys (e.g., "items.0.name").
 */
export function flattenJson(obj: unknown, prefix = '', result: Record<string, string> = {}): Record<string, string> {
    if (obj === null || obj === undefined) {
        if (prefix) {
            result[prefix] = String(obj)
        }
        return result
    }

    if (typeof obj !== 'object') {
        if (prefix) {
            result[prefix] = String(obj)
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

/**
 * Parses the log body as JSON (if valid) and extracts flattened attributes.
 * Returns up to MAX_JSON_ATTRIBUTES attributes, without overwriting existing attributes.
 */
export function extractJsonAttributesFromBody(body: string | null): Record<string, string> {
    if (!body) {
        return {}
    }

    let parsed: unknown
    try {
        parsed = parseJSON(body)
    } catch {
        return {}
    }

    if (typeof parsed !== 'object' || parsed === null) {
        return {}
    }

    const flattened = flattenJson(parsed)
    const newAttributes: Record<string, string> = {}
    let count = 0

    for (const [key, value] of Object.entries(flattened)) {
        if (count >= MAX_JSON_ATTRIBUTES) {
            break
        }
        count++
        newAttributes[key] = JSON.stringify(value.toString())
    }

    return newAttributes
}

/**
 * Processes a LogRecord by parsing its body as JSON and adding flattened attributes.
 * Modifies the record in place and returns it.
 */
export function enrichLogRecordWithJsonAttributes(record: LogRecord): LogRecord {
    if (!record.body) {
        return record
    }

    const existingAttributes = record.attributes || {}
    const jsonAttributes = extractJsonAttributesFromBody(record.body)

    if (Object.keys(jsonAttributes).length > 0) {
        record.attributes = {
            ...jsonAttributes,
            ...existingAttributes, // existing attributes take precedence
        }
    }

    return record
}

/**
 * Processes an AVRO-encoded log message buffer containing multiple records
 * If json-parse is disabled it does nothing (does not decode or encode the buffer)
 * If it's enabled, it has to decode, process and re-encode the buffer
 */
export async function processLogMessageBuffer(buffer: Buffer, jsonParse: boolean): Promise<Buffer> {
    if (!jsonParse) {
        return buffer
    }

    const [logRecordType, records] = await decodeLogRecords(buffer)
    if (!logRecordType) {
        throw new Error('avro schema metadata not found')
    }

    // Enrich each record with JSON attributes from body
    for (const record of records) {
        enrichLogRecordWithJsonAttributes(record)
    }

    return await encodeLogRecords(logRecordType, records)
}
