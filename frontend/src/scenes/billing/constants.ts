// sync with ee/hogai/graph/billing/nodes.py
export const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Mobile Recordings', value: 'mobile_recording_count_in_period' },
    { label: 'Feature Flag Requests', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Exceptions', value: 'exceptions_captured_in_period' },
    { label: 'Synced Rows', value: 'rows_synced_in_period' },
    { label: 'Identified Events', value: 'enhanced_persons_event_count_in_period' },
    { label: 'Survey Responses', value: 'survey_responses_count_in_period' },
    { label: 'LLM Events', value: 'ai_event_count_in_period' },
    { label: 'Data Pipelines', value: 'data_pipelines' },
    { label: 'Group Analytics', value: 'group_analytics' },
] as const

export type UsageTypeOption = (typeof USAGE_TYPES)[number]
export type UsageTypeValue = UsageTypeOption['value']

export const ALL_USAGE_TYPES: UsageTypeValue[] = USAGE_TYPES.map((opt) => opt.value)

// Date after which billing for data pipelines ends and add-on upgrades/downgrades are disabled
export const DATA_PIPELINES_CUTOFF_DATE = '2025-09-04'

// Date when billing for realtime destinations and batch exports begins (day after data pipelines cutoff)
export const REALTIME_DESTINATIONS_BILLING_START_DATE = '2025-09-05'
