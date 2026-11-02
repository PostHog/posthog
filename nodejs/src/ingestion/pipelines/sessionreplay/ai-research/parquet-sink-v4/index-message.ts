/** Reads one v4 index row from its Kafka message, as the recorder sends it. */
import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer/consumer-v1'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { CapturedData } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'

import { V4Index, V4IndexRow, selectIndexRow } from './index-columns'
import { V4ParquetSinkMetrics, V4RowRejection } from './metrics'

/** Which index the row belongs to: `blocks` or `images`. */
export const INDEX_HEADER = 'ml-index'
/** The UTC day of the objects the row points at, the `dt=` partition of its file. */
export const WRITE_DAY_HEADER = 'ml-write-day'

export interface V4IndexMessage {
    index: V4Index
    writeDay: string
    row: V4IndexRow
}

/** Block rows feed the event metadata watermark and image rows the inline image one, as in v3. */
export const INDEX_CAPTURED_DATA: Readonly<Record<V4Index, CapturedData>> = {
    blocks: 'event_metadata',
    images: 'inline_images',
}

function isIndex(value: string | undefined): value is V4Index {
    return value === 'blocks' || value === 'images'
}

export function indexCapturedData(message: Message): CapturedData | undefined {
    const index = parseKafkaHeaders(message.headers)[INDEX_HEADER]
    return isIndex(index) ? INDEX_CAPTURED_DATA[index] : undefined
}

function isWriteDay(value: string | undefined): value is string {
    if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return false
    }
    const day = new Date(`${value}T00:00:00Z`)
    return !Number.isNaN(day.getTime()) && day.toISOString().slice(0, 10) === value
}

function reject(reason: V4RowRejection, message: Message, invalidColumn?: string): null {
    // Skip a bad row rather than wedge the partition, as the v3 sink does.
    logger.warn('🪶', 'ai_research_v4_parquet_row_rejected', {
        reason,
        partition: message.partition,
        offset: message.offset,
        ...(invalidColumn && { column: invalidColumn }),
    })
    V4ParquetSinkMetrics.incRowsRejected(reason)
    return null
}

export function parseIndexMessage(message: Message): V4IndexMessage | null {
    const headers = parseKafkaHeaders(message.headers)
    const index = headers[INDEX_HEADER]
    if (!isIndex(index)) {
        return reject('unknown_index', message)
    }
    const writeDay = headers[WRITE_DAY_HEADER]
    if (!isWriteDay(writeDay)) {
        return reject('invalid_write_day', message)
    }
    let value: unknown
    try {
        value = parseJSON(message.value?.toString('utf8') ?? '')
    } catch {
        return reject('parse_failed', message)
    }
    const selected = selectIndexRow(index, value)
    if (!('row' in selected)) {
        V4ParquetSinkMetrics.incInvalidColumn(index, selected.invalidColumn)
        return reject('invalid_row', message, selected.invalidColumn)
    }
    V4ParquetSinkMetrics.incRowsParsed(index)
    return { index, writeDay, row: selected.row }
}
