import { CommonConfig } from '~/common/config'
import { buildIntegerMatcher } from '~/common/config/config'
import { ValueMatcher } from '~/types'

import { UsageIngestionClient } from './client'
import { UsageRecordBatch } from './usage-record-batch'

export type UsageIngestionConfig = Pick<
    CommonConfig,
    | 'USAGE_INGESTION_ADDR'
    | 'USAGE_INGESTION_TLS'
    | 'USAGE_INGESTION_TIMEOUT_MS'
    | 'USAGE_INGESTION_MAX_BATCH_SIZE'
    | 'USAGE_INGESTION_REPORT_TEAMS'
>

export type UsageReportSite =
    | 'events'
    | 'ai_events'
    | 'exceptions'
    | 'cdp'
    | 'surveys'
    | 'logs'
    | 'apm_traces'
    | 'session_replay'
    | 'enhanced_persons'

const PRODUCER_IDS = {
    events: 'ingestion',
    ai_events: 'ai-ingestion',
    exceptions: 'error-tracking',
    cdp: 'cdp',
    surveys: 'ingestion',
    logs: 'logs',
    apm_traces: 'apm-traces',
    session_replay: 'session-replay',
    enhanced_persons: 'ingestion',
} as const

export function usageReportTeamMatcher(config: UsageIngestionConfig): ValueMatcher<number> {
    return buildIntegerMatcher(config.USAGE_INGESTION_REPORT_TEAMS, true)
}

export function createUsageIngestionClient(
    config: UsageIngestionConfig,
    site: UsageReportSite
): UsageIngestionClient | null {
    if (!config.USAGE_INGESTION_ADDR || !config.USAGE_INGESTION_REPORT_TEAMS) {
        return null
    }
    return new UsageIngestionClient({
        addr: config.USAGE_INGESTION_ADDR,
        producerId: PRODUCER_IDS[site],
        useTls: config.USAGE_INGESTION_TLS,
        timeoutMs: config.USAGE_INGESTION_TIMEOUT_MS,
        maxBatchSize: config.USAGE_INGESTION_MAX_BATCH_SIZE,
    })
}

/**
 * The batch every event pipeline bills through, one per batch and one client per process,
 * because each client owns a transport. Shared so a new pipeline host cannot half-wire it:
 * a client built without an address reports nothing, and that silence is indistinguishable
 * from a working collector with no traffic.
 *
 * `events` is the unit the meters an event pipeline bills share; a record for a meter
 * counted in something else passes its own unit to {@link UsageRecordBatch.add}.
 */
export function createEventUsageBatchFactory(
    config: UsageIngestionConfig,
    site: UsageReportSite
): () => UsageRecordBatch {
    const client = createUsageIngestionClient(config, site)
    const isTeamEnabled = usageReportTeamMatcher(config)
    return () => new UsageRecordBatch(client, { unit: 'events', isTeamEnabled })
}
