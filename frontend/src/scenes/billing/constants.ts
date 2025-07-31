// sync with ee/hogai/graph/billing/nodes.py
export const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Mobile Recordings', value: 'mobile_recording_count_in_period' },
    { label: 'Feature Flags', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Exceptions', value: 'exceptions_captured_in_period' },
    { label: 'Rows Synced', value: 'rows_synced_in_period' },
    { label: 'Persons', value: 'enhanced_persons_event_count_in_period' },
    { label: 'Survey Responses', value: 'survey_responses_count_in_period' },
    { label: 'Data Pipelines', value: 'data_pipelines' },
    { label: 'Group Analytics', value: 'group_analytics' },
] as const

export type UsageTypeOption = (typeof USAGE_TYPES)[number]
export type UsageTypeValue = UsageTypeOption['value']

export const ALL_USAGE_TYPES: UsageTypeValue[] = USAGE_TYPES.map((opt) => opt.value)
