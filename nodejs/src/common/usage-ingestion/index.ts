import { CommonConfig } from '~/common/config'
import { buildIntegerMatcher } from '~/common/config/config'
import { ValueMatcher } from '~/types'

import { UsageIngestionClient } from './client'

export type UsageIngestionConfig = Pick<
    CommonConfig,
    | 'USAGE_INGESTION_ADDR'
    | 'USAGE_INGESTION_TLS'
    | 'USAGE_INGESTION_TIMEOUT_MS'
    | 'USAGE_INGESTION_MAX_BATCH_SIZE'
    | 'USAGE_INGESTION_REPORT_TEAMS'
>

export type UsageReportSite = 'events' | 'ai_events' | 'exceptions' | 'cdp'

const PRODUCER_IDS = {
    events: 'ingestion',
    ai_events: 'ai-ingestion',
    exceptions: 'error-tracking',
    cdp: 'cdp',
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
