// sync with ee/hogai/graph/billing/nodes.py
export const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Identified Events', value: 'enhanced_persons_event_count_in_period' },
    { label: 'Group Analytics', value: 'group_analytics' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Mobile Recordings', value: 'mobile_recording_count_in_period' },
    { label: 'Feature Flag Requests', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Exceptions', value: 'exceptions_captured_in_period' },
    { label: 'Survey Responses', value: 'survey_responses_count_in_period' },
    { label: 'LLM Events', value: 'ai_event_count_in_period' },
    { label: 'Synced Rows', value: 'rows_synced_in_period' },
    { label: 'Free Synced Rows', value: 'free_historical_rows_synced_in_period' },
    { label: 'Data Pipelines (deprecated)', value: 'data_pipelines' },
    { label: 'Destinations Trigger Events', value: 'cdp_billable_invocations_in_period' },
    { label: 'Rows Exported', value: 'rows_exported_in_period' },
] as const

export type UsageTypeOption = (typeof USAGE_TYPES)[number]
export type UsageTypeValue = UsageTypeOption['value']

export const ALL_USAGE_TYPES: UsageTypeValue[] = USAGE_TYPES.map((opt) => opt.value)

// Date after which billing for data pipelines ends and add-on upgrades/downgrades are disabled,
// in sync with billing_end_date of data_pipelines in billing plans config
export const DATA_PIPELINES_CUTOFF_DATE = '2025-09-10'

// Date when billing for realtime destinations and batch exports begins (day after data pipelines cutoff),
// in sync with billing_start_date of realtime_destinations and batch_exports in billing plans config
export const REALTIME_DESTINATIONS_BILLING_START_DATE = '2025-09-11'
