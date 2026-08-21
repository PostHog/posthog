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
    | 'USAGE_INGESTION_REPORT_EVENTS_TEAMS'
    | 'USAGE_INGESTION_REPORT_AI_EVENTS_TEAMS'
    | 'USAGE_INGESTION_REPORT_EXCEPTIONS_TEAMS'
    | 'USAGE_INGESTION_REPORT_CDP_TEAMS'
    | 'USAGE_INGESTION_REPORT_SURVEYS_TEAMS'
    | 'USAGE_INGESTION_REPORT_LOGS_TEAMS'
    | 'USAGE_INGESTION_REPORT_APM_TEAMS'
    | 'USAGE_INGESTION_REPORT_SESSION_REPLAY_TEAMS'
    | 'USAGE_INGESTION_REPORT_ENHANCED_PERSONS_TEAMS'
>

export type UsageReportSite = 'events' | 'ai_events' | 'exceptions' | 'cdp' | 'surveys' | 'logs' | 'apm' | 'session_replay' | 'enhanced_persons'

const TEAM_MATCHER_KEYS = {
    events: 'USAGE_INGESTION_REPORT_EVENTS_TEAMS',
    ai_events: 'USAGE_INGESTION_REPORT_AI_EVENTS_TEAMS',
    exceptions: 'USAGE_INGESTION_REPORT_EXCEPTIONS_TEAMS',
    cdp: 'USAGE_INGESTION_REPORT_CDP_TEAMS',
    surveys: 'USAGE_INGESTION_REPORT_SURVEYS_TEAMS',
    logs: 'USAGE_INGESTION_REPORT_LOGS_TEAMS',
    apm: 'USAGE_INGESTION_REPORT_APM_TEAMS',
    session_replay: 'USAGE_INGESTION_REPORT_SESSION_REPLAY_TEAMS',
    enhanced_persons: 'USAGE_INGESTION_REPORT_ENHANCED_PERSONS_TEAMS',
} as const

const PRODUCER_IDS = {
    events: 'ingestion',
    ai_events: 'ai-ingestion',
    exceptions: 'error-tracking',
    cdp: 'cdp',
    surveys: 'ingestion',
    logs: 'logs',
    apm: 'apm',
    session_replay: 'session-replay',
    enhanced_persons: 'ingestion',
} as const

export function usageReportTeamMatcher(config: UsageIngestionConfig, site: UsageReportSite): ValueMatcher<number> {
    return buildIntegerMatcher(config[TEAM_MATCHER_KEYS[site]], true)
}

export function createUsageIngestionClient(
    config: UsageIngestionConfig,
    site: UsageReportSite
): UsageIngestionClient | null {
    if (!config.USAGE_INGESTION_ADDR || !config[TEAM_MATCHER_KEYS[site]]) {
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
