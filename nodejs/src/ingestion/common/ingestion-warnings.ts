import { Counter } from 'prom-client'

import { KAFKA_INGESTION_WARNINGS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { INGESTION_WARNINGS_OUTPUT, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { IngestionWarningLimiter } from '~/common/utils/token-bucket'
import { castTimestampOrNow } from '~/common/utils/utils'
import { TeamId, TimestampFormat } from '~/types'

export const ingestionWarningCounter = new Counter({
    name: 'ingestion_warnings_total',
    help: 'Total number of ingestion warnings by type and emission status',
    labelNames: ['type', 'emitted'],
})

/**
 * Unified ingestion warning structure used across pipeline warnings and direct producer calls.
 */
export interface IngestionWarning {
    type: string
    details: Record<string, any>
    category?: string
    severity?: 'info' | 'warning' | 'error'
    pipelineStep?: string
    key?: string
    alwaysSend?: boolean
}

/**
 * Structured warning fields for direct producer calls.
 * Subset of IngestionWarning focusing on enrichment metadata.
 */
export interface StructuredWarningFields {
    category?: string
    severity?: 'info' | 'warning' | 'error'
    pipelineStep?: string
}

function serializeIngestionWarning(teamId: TeamId, warning: IngestionWarning): string {
    const fullDetails = {
        ...(warning.category && { category: warning.category }),
        ...(warning.severity && { severity: warning.severity }),
        ...(warning.pipelineStep && { pipelineStep: warning.pipelineStep }),
        ...warning.details,
    }
    return JSON.stringify({
        team_id: teamId,
        type: warning.type,
        source: 'plugin-server',
        details: JSON.stringify(fullDetails),
        timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
    })
}

function shouldEmitWarning(teamId: TeamId, warning: IngestionWarning): boolean {
    const limiterKey = `${teamId}:${warning.type}:${warning.key || ''}`
    return !!warning.alwaysSend || IngestionWarningLimiter.consume(limiterKey, 1)
}

/**
 * Legacy wrapper — uses hardcoded KAFKA_INGESTION_WARNINGS topic and a raw producer.
 * Prefer emitIngestionWarning with outputs in new pipeline code.
 */
export async function captureIngestionWarning(
    kafkaProducer: KafkaProducerWrapper,
    teamId: TeamId,
    warning: IngestionWarning
): Promise<boolean> {
    const emitted = shouldEmitWarning(teamId, warning)
    ingestionWarningCounter.inc({ type: warning.type, emitted: emitted.toString() })

    if (emitted) {
        return kafkaProducer
            .queueMessages({
                topic: KAFKA_INGESTION_WARNINGS,
                messages: [{ value: serializeIngestionWarning(teamId, warning) }],
            })
            .then(() => true)
            .catch((error: unknown) => {
                logger.warn('⚠️', 'Failed to produce ingestion warning', {
                    error,
                    team_id: teamId,
                    type: warning.type,
                    details: warning.details,
                })
                return false
            })
    }
    return Promise.resolve(false)
}

/** Produce an ingestion warning through the outputs abstraction. */
export async function emitIngestionWarning(
    outputs: IngestionOutputs<IngestionWarningsOutput>,
    teamId: TeamId,
    warning: IngestionWarning
): Promise<boolean> {
    const emitted = shouldEmitWarning(teamId, warning)
    ingestionWarningCounter.inc({ type: warning.type, emitted: emitted.toString() })

    if (emitted) {
        return outputs
            .queueMessages(INGESTION_WARNINGS_OUTPUT, [
                { value: Buffer.from(serializeIngestionWarning(teamId, warning)) },
            ])
            .then(() => true)
            .catch((error: unknown) => {
                logger.warn('⚠️', 'Failed to produce ingestion warning', {
                    error,
                    team_id: teamId,
                    type: warning.type,
                    details: warning.details,
                })
                return false
            })
    }
    return Promise.resolve(false)
}
