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

export type IngestionWarningCategory = 'size' | 'merge' | 'event' | 'transformation' | 'replay'
export type IngestionWarningSeverity = 'info' | 'warning' | 'error'

/**
 * Central registry of every ingestion warning type this service can emit.
 * Category and severity are fixed attributes of the type, resolved here at
 * serialization time so callsites cannot drift or forget them. Adding a new
 * warning requires registering it here, which keeps the ClickHouse v2
 * structured columns, the API filters, and agent-facing docs in sync.
 *
 * Severity convention: 'error' = the event (or message) was dropped,
 * 'warning' = ingested but modified or partially rejected,
 * 'info' = informational or an intentional, team-configured drop.
 */
export const INGESTION_WARNING_TYPES = {
    // Size limits — payload or property blobs exceeding Kafka/Postgres limits
    message_size_too_large: { category: 'size', severity: 'error' },
    person_properties_size_violation: { category: 'size', severity: 'error' },
    person_upsert_message_size_too_large: { category: 'size', severity: 'error' },
    group_upsert_message_size_too_large: { category: 'size', severity: 'error' },
    group_key_too_long: { category: 'size', severity: 'error' },

    // Person merges — rejected $identify / $create_alias / $merge_dangerously operations
    cannot_merge_already_identified: { category: 'merge', severity: 'warning' },
    cannot_merge_with_illegal_distinct_id: { category: 'merge', severity: 'warning' },
    merge_race_condition: { category: 'merge', severity: 'error' },

    // Event validation — malformed or rejected event data
    client_ingestion_warning: { category: 'event', severity: 'info' },
    ignored_invalid_timestamp: { category: 'event', severity: 'warning' },
    schema_validation_failed: { category: 'event', severity: 'error' },
    skipping_event_invalid_distinct_id: { category: 'event', severity: 'error' },
    invalid_ai_token_property: { category: 'event', severity: 'warning' },
    invalid_process_person_profile: { category: 'event', severity: 'warning' },
    invalid_event_when_process_person_profile_is_false: { category: 'event', severity: 'error' },
    event_dropped_too_old: { category: 'event', severity: 'info' },

    // Cookieless mode — events missing the data required to compute a cookieless distinct id
    cookieless_missing_timestamp: { category: 'event', severity: 'error' },
    cookieless_timestamp_out_of_range: { category: 'event', severity: 'error' },
    cookieless_missing_user_agent: { category: 'event', severity: 'error' },
    cookieless_missing_ip: { category: 'event', severity: 'error' },
    cookieless_missing_host: { category: 'event', severity: 'error' },

    // Heatmaps — rejected $heatmap_data payloads
    invalid_heatmap_data: { category: 'event', severity: 'warning' },
    rejecting_heatmap_data_with_invalid_url: { category: 'event', severity: 'warning' },
    rejecting_heatmap_data_with_invalid_items: { category: 'event', severity: 'warning' },

    // Error tracking — exception event processing
    error_tracking_exception_processing_errors: { category: 'event', severity: 'warning' },

    // Transformations — user-configured hog transformations
    event_dropped_by_transformation: { category: 'transformation', severity: 'info' },

    // Session replay — rejected or suspicious replay messages
    replay_lib_version_too_old: { category: 'replay', severity: 'info' },
    message_contained_no_valid_rrweb_events: { category: 'replay', severity: 'warning' },
    message_timestamp_diff_too_large: { category: 'replay', severity: 'warning' },
} as const satisfies Record<string, { category: IngestionWarningCategory; severity: IngestionWarningSeverity }>

export type IngestionWarningType = keyof typeof INGESTION_WARNING_TYPES

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
