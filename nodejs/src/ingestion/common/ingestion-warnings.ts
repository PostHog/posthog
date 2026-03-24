import { Counter } from 'prom-client'

import { KAFKA_INGESTION_WARNINGS } from '../../config/kafka-topics'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { TeamId, TimestampFormat } from '../../types'
import { logger } from '../../utils/logger'
import { IngestionWarningLimiter } from '../../utils/token-bucket'
import { castTimestampOrNow } from '../../utils/utils'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { INGESTION_WARNINGS_OUTPUT, IngestionWarningsOutput } from './outputs'

export const ingestionWarningCounter = new Counter({
    name: 'ingestion_warnings_total',
    help: 'Total number of ingestion warnings by type and emission status',
    labelNames: ['type', 'emitted'],
})

function serializeIngestionWarning(teamId: TeamId, type: string, details: Record<string, any>): string {
    return JSON.stringify({
        team_id: teamId,
        type: type,
        source: 'plugin-server',
        details: JSON.stringify(details),
        timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
    })
}

function shouldEmitWarning(teamId: TeamId, type: string, debounce?: { key?: string; alwaysSend?: boolean }): boolean {
    const limiterKey = `${teamId}:${type}:${debounce?.key || ''}`
    return !!debounce?.alwaysSend || IngestionWarningLimiter.consume(limiterKey, 1)
}

/**
 * Legacy wrapper — uses hardcoded KAFKA_INGESTION_WARNINGS topic and a raw producer.
 * Prefer emitIngestionWarning with outputs in new pipeline code.
 */
export async function captureIngestionWarning(
    kafkaProducer: KafkaProducerWrapper,
    teamId: TeamId,
    type: string,
    details: Record<string, any>,
    debounce?: { key?: string; alwaysSend?: boolean }
): Promise<boolean> {
    const emitted = shouldEmitWarning(teamId, type, debounce)
    ingestionWarningCounter.inc({ type, emitted: emitted.toString() })

    if (emitted) {
        return kafkaProducer
            .queueMessages({
                topic: KAFKA_INGESTION_WARNINGS,
                messages: [{ value: serializeIngestionWarning(teamId, type, details) }],
            })
            .then(() => true)
            .catch((error: unknown) => {
                logger.warn('⚠️', 'Failed to produce ingestion warning', { error, team_id: teamId, type, details })
                return false
            })
    }
    return Promise.resolve(false)
}

/** Produce an ingestion warning through the outputs abstraction. */
export async function emitIngestionWarning(
    outputs: IngestionOutputs<IngestionWarningsOutput>,
    teamId: TeamId,
    type: string,
    details: Record<string, any>,
    debounce?: { key?: string; alwaysSend?: boolean }
): Promise<boolean> {
    const emitted = shouldEmitWarning(teamId, type, debounce)
    ingestionWarningCounter.inc({ type, emitted: emitted.toString() })

    if (emitted) {
        return outputs
            .queueMessages(INGESTION_WARNINGS_OUTPUT, [
                { value: Buffer.from(serializeIngestionWarning(teamId, type, details)) },
            ])
            .then(() => true)
            .catch((error: unknown) => {
                logger.warn('⚠️', 'Failed to produce ingestion warning', { error, team_id: teamId, type, details })
                return false
            })
    }
    return Promise.resolve(false)
}
