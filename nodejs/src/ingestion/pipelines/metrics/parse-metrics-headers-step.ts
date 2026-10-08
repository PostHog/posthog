import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { logger } from '~/common/utils/logger'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { metricMessageDroppedCounter } from './metrics'

export interface MetricsHeaders {
    token: string
    bytesUncompressed: number
    bytesCompressed: number
    recordCount: number
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
            return Promise.resolve(
                ok({
                    ...input,
                    token,
                    bytesUncompressed: parseInt(headers.bytes_uncompressed ?? '0', 10),
                    bytesCompressed: parseInt(headers.bytes_compressed ?? '0', 10),
                    recordCount: parseInt(headers.record_count ?? '0', 10),
                })
            )
        } catch (e) {
            logger.error('Error parsing message', e)
            metricMessageDroppedCounter.inc({ reason: 'parse_error', team_id: 'unknown' })
            return Promise.resolve(drop('parse_error'))
        }
    }
}
