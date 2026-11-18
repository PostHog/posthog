import type { LogRecord } from './log-record-avro'

export const MAX_LOG_RECORD_BYTES = 1024 * 1024

export function logRecordSizeBytes(
    record: Pick<LogRecord, 'body' | 'severity_text' | 'attributes' | 'resource_attributes'>
): number {
    let bytes = 0
    for (const value of [record.body, record.severity_text]) {
        if (typeof value === 'string') {
            bytes += Buffer.byteLength(value)
        }
    }
    for (const attributes of [record.attributes, record.resource_attributes]) {
        if (attributes) {
            for (const [key, value] of Object.entries(attributes)) {
                bytes += Buffer.byteLength(key) + Buffer.byteLength(value)
            }
        }
    }
    return bytes
}
