// sync with ee/hogai/tools/read_billing_tool/tool.py
// Values are sent to the `billing` repo as `usage_types`; keep in sync with accepted types in `billing/types/usage.py`.
export const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Identified events', value: 'enhanced_persons_event_count_in_period' },
    { label: 'Group analytics', value: 'group_analytics' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Mobile recordings', value: 'mobile_recording_count_in_period' },
    { label: 'Feature flag requests', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Exceptions', value: 'exceptions_captured_in_period' },
    { label: 'Survey responses', value: 'survey_responses_count_in_period' },
    { label: 'AI events', value: 'ai_event_count_in_period' },
    { label: 'Synced rows', value: 'rows_synced_in_period' },
    { label: 'Free synced rows', value: 'free_historical_rows_synced_in_period' },
    { label: 'Data pipelines (deprecated)', value: 'data_pipelines' },
    { label: 'Destinations trigger events', value: 'cdp_billable_invocations_in_period' },
    { label: 'Rows exported', value: 'rows_exported_in_period' },
    { label: 'PostHog AI', value: 'ai_credits_used_in_period' },
    { label: 'Inbox credits', value: 'signals_credits_used_in_period' },
    { label: 'Workflow emails', value: 'workflow_emails_sent_in_period' },
    { label: 'Workflow destinations', value: 'workflow_billable_invocations_in_period' },
    { label: 'Logs ingested (MB)', value: 'logs_mb_in_period' },
] as const

export type UsageTypeOption = (typeof USAGE_TYPES)[number]
export type UsageTypeValue = UsageTypeOption['value']

export const ALL_USAGE_TYPES: UsageTypeValue[] = USAGE_TYPES.map((opt) => opt.value)

export const CODE_PRODUCT_KEY = 'posthog_code'
// TODO: Replace hardcoded plan keys with dynamic plan metadata from billing service
export const CODE_PLAN_FREE = 'posthog-code-free-20260301'
export const CODE_PLAN_PRO = 'posthog-code-pro-200-20260301'
export const CODE_PLAN_ALPHA_PRO = 'posthog-code-pro-0-20260422'

export const CODE_PRO_PLAN_PREFIX = 'posthog-code-pro-'
export const CODE_FREE_PLAN_PREFIX = 'posthog-code-free'

// Date after which billing for data pipelines ends and add-on upgrades/downgrades are disabled,
// in sync with billing_end_date of data_pipelines in billing plans config
export const DATA_PIPELINES_CUTOFF_DATE = '2025-09-10'

// Date when billing for realtime destinations and batch exports begins (day after data pipelines cutoff),
// in sync with billing_start_date of realtime_destinations and batch_exports in billing plans config
export const REALTIME_DESTINATIONS_BILLING_START_DATE = '2025-09-11'
