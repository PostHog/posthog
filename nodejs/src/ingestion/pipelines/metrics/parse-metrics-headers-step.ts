import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { logger } from '~/common/utils/logger'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { metricMessageDroppedCounter } from './metrics'

export interface MetricsHeaders {
    kafkaHeaders: Record<string, string>
    token: string
    bytesUncompressed: number
    bytesCompressed: number
    recordCount: number
}

const SIZE_HEADERS = ['bytes_uncompressed', 'bytes_compressed', 'record_count'] as const

/** A missing header counts as 0. A negative value makes the Prometheus counters throw, so only non-negative safe integers are valid. */
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
                logger.error('invalid_size_header', { headers: invalid })
                metricMessageDroppedCounter.inc({ reason: 'invalid_size_header', team_id: 'unknown' })
                return Promise.resolve(drop('invalid_size_header'))
            }
            return Promise.resolve(
                ok({ ...input, kafkaHeaders: headers, token, bytesUncompressed, bytesCompressed, recordCount })
            )
        } catch (e) {
            logger.error('Error parsing message', e)
            metricMessageDroppedCounter.inc({ reason: 'parse_error', team_id: 'unknown' })
            return Promise.resolve(drop('parse_error'))
        }
    }
}
