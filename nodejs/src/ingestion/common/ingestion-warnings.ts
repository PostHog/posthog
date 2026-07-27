import { Counter } from 'prom-client'

import { KAFKA_INGESTION_WARNINGS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { INGESTION_WARNINGS_OUTPUT, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { IngestionWarningLimiter } from '~/common/utils/token-bucket'
import { castTimestampOrNow } from '~/common/utils/utils'
import {
    CAPTURE_PRODUCED_WARNING_TYPES,
    INGESTION_WARNING_TYPES,
    type IngestionWarningCategory,
    type IngestionWarningSeverity,
    type IngestionWarningType,
} from '~/ingestion/common/ingestion-warning-types'
import { TeamId, TimestampFormat } from '~/types'

// The warning registry lives in the dependency-free `./ingestion-warning-types` leaf so the
// codegen generator and its no-drift test can import it without loading the ingestion runtime.
// Re-exported here so existing `~/ingestion/common/ingestion-warnings` importers are unaffected.
export {
    CAPTURE_PRODUCED_WARNING_TYPES,
    INGESTION_WARNING_TYPES,
    type IngestionWarningCategory,
    type IngestionWarningSeverity,
    type IngestionWarningType,
}

export const ingestionWarningCounter = new Counter({
    name: 'ingestion_warnings_total',
    help: 'Total number of ingestion warnings by type and emission status',
    labelNames: ['type', 'emitted'],
})

/**
 * Unified ingestion warning structure used across pipeline warnings and direct producer calls.
 * Category and severity come from INGESTION_WARNING_TYPES; only the per-occurrence
 * fields (pipelineStep, details) are set by callsites.
 */
export interface IngestionWarning {
    type: IngestionWarningType
    details: Record<string, any>
    pipelineStep?: string
    key?: string
    alwaysSend?: boolean
    // Producing service, stamped into the v2 message `source` column. Defaults
    // to 'plugin-server'; other producers (e.g. 'capture') set it explicitly.
    source?: string
}

function serializeIngestionWarning(teamId: TeamId, warning: IngestionWarning): string {
    const { category, severity } = INGESTION_WARNING_TYPES[warning.type]
    // Structured fields are spread last so a stray key in details cannot override them.
    // ClickHouse v2 materializes columns from these exact key names (see sql_v2.py).
    const fullDetails = {
        ...warning.details,
        category,
        severity,
        ...(warning.pipelineStep && { pipelineStep: warning.pipelineStep }),
    }
    return JSON.stringify({
        team_id: teamId,
        type: warning.type,
        source: warning.source ?? 'plugin-server',
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
