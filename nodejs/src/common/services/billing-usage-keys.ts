// Each key must be marked `quota_enforcement: posthog` in the contract Django vendors, so Node can't read a limited set
// under a name Django never writes. The test beside this file checks it. Add a key to the contract before adding it
// here, and remove it here before removing it from the contract.
export const BILLED_USAGE_KEYS = [
    'ai_credits',
    'cdp_trigger_events',
    'events',
    'exceptions',
    'feature_flag_requests',
    'llm_events',
    'logs_mb_ingested',
    'posthog_code_credits',
    'recordings',
    'replay_vision_credits',
    'rows_exported',
    'rows_synced',
    'signals_credits',
    'signals_spend_credits',
    'survey_responses',
    'workflow_destinations',
    'workflow_emails',
] as const

export type BilledUsageKey = (typeof BILLED_USAGE_KEYS)[number]

/** Relative to the repository root. */
export const ENTITLEMENTS_CONTRACT_RELATIVE_PATH = 'posthog/billing/contract/entitlements_contract.json'
