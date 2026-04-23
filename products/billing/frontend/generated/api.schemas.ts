/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface BillingApi {
    /** @maxLength 100 */
    plan: string
    billing_limit: number
}

export interface PaginatedBillingListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BillingApi[]
}

export interface PatchedBillingApi {
    /** @maxLength 100 */
    plan?: string
    billing_limit?: number
}

export type BillingListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BillingSpendRetrieveParams = {
    /**
     * @nullable
     */
    breakdowns?: string | null
    /**
     * @nullable
     */
    end_date?: string | null
    /**
     * @nullable
     */
    interval?: string | null
    /**
     * @nullable
     */
    start_date?: string | null
    /**
     * @nullable
     */
    team_ids?: string | null
    /**
     * Comma-separated usage type identifiers to filter on. Valid values: event_count_in_period, enhanced_persons_event_count_in_period, group_analytics, recording_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, exceptions_captured_in_period, survey_responses_count_in_period, ai_event_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, data_pipelines, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period. E.g. "event_count_in_period,recording_count_in_period". Omit for all types.
     * @nullable
     */
    usage_types?: string | null
}

export type BillingUsageRetrieveParams = {
    /**
     * @nullable
     */
    breakdowns?: string | null
    /**
     * @nullable
     */
    end_date?: string | null
    /**
     * @nullable
     */
    interval?: string | null
    /**
     * @nullable
     */
    start_date?: string | null
    /**
     * @nullable
     */
    team_ids?: string | null
    /**
     * Comma-separated usage type identifiers to filter on. Valid values: event_count_in_period, enhanced_persons_event_count_in_period, group_analytics, recording_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, exceptions_captured_in_period, survey_responses_count_in_period, ai_event_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, data_pipelines, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period. E.g. "event_count_in_period,recording_count_in_period". Omit for all types.
     * @nullable
     */
    usage_types?: string | null
}
