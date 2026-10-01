import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { logger } from '~/common/utils/logger'
import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'

export interface MetricsHeaders {
    token: string
    bytesUncompressed: number
    bytesCompressed: number
    recordCount: number
}

const SIZE_HEADERS = ['bytes_uncompressed', 'bytes_compressed', 'record_count'] as const

/**
 * A missing size header counts as 0; a present one must be a whole non-negative
 * safe integer, because these values feed billing rows and Prometheus counters
 * that reject negatives and silently absorb NaN.
 */
function parseSizeHeader(value: string | undefined): number | null {
    if (value === undefined) {
        return 0
    }
    if (!/^\d+$/.test(value)) {
        return null
    }
    const parsed = Number(value)
    return Number.isSafeInteger(parsed) ? parsed : null
}

/**
 * Reads the capture-side headers a metrics message carries. The Avro value is
 * not touched here; every decision until the repack stage is header-driven.
 */
export function createParseMetricsHeadersStep<T extends { message: Message }>(): ProcessingStep<T, T & MetricsHeaders> {
    return function parseMetricsHeadersStep(input) {
        try {
            const headers = parseKafkaHeaders(input.message.headers)
            const token = headers.token
            if (!token) {
                logger.error('missing_token')
                metricMessageDroppedCounter.inc({ reason: 'missing_token', team_id: 'unknown' })
                return Promise.resolve(drop('missing_token'))
            }
            const [bytesUncompressed, bytesCompressed, recordCount] = SIZE_HEADERS.map((name) =>
                parseSizeHeader(headers[name])
            )
            if (bytesUncompressed === null || bytesCompressed === null || recordCount === null) {
                const invalid = SIZE_HEADERS.filter((name) => parseSizeHeader(headers[name]) === null)
                metricMessageDlqCounter.inc({ reason: 'invalid_size_header', team_id: 'unknown' })
                return Promise.resolve(
                    dlq('invalid_size_header', new Error(`Invalid metrics size header(s): ${invalid.join(', ')}`))
                )
            }
            return Promise.resolve(ok({ ...input, token, bytesUncompressed, bytesCompressed, recordCount }))
        } catch (e) {
            logger.error('Error parsing message', e)
            metricMessageDroppedCounter.inc({ reason: 'parse_error', team_id: 'unknown' })
            return Promise.resolve(drop('parse_error'))
        }
    }
}
