import { AnyPropertyFilter } from '~/types'

import { LLMProvider } from '../settings/llmProviderKeysLogic'

export type EvaluationType = 'llm_judge' | 'hog' | 'sentiment'
export type EvaluationTarget = 'generation' | 'trace'
export type EvaluationOutputType = 'boolean' | 'sentiment'
export type EvaluationStatus = 'active' | 'paused' | 'error'
export type EvaluationStatusReason =
    | 'trial_limit_reached'
    | 'model_not_allowed'
    | 'provider_key_deleted'
    | 'no_default_model'
    | 'provider_key_invalid'
    | 'provider_key_permission_denied'
    | 'provider_key_quota_exceeded'
    | 'provider_key_rate_limited'
    | 'model_not_found'
    | 'hog_error'

export interface ModelConfiguration {
    provider: LLMProvider
    model: string
    provider_key_id: string | null
    provider_key_name?: string | null
}

export interface EvaluationOutputConfig {
    allows_na?: boolean
}

export interface EvaluationTargetConfig {
    /** For 'trace' target: seconds to wait after the first matching generation before evaluating the trace. */
    window_seconds?: number
}

export interface LLMJudgeEvaluationConfig {
    prompt: string
}

export interface HogEvaluationConfig {
    source: string
    bytecode?: unknown[]
}

export interface SentimentEvaluationConfig {
    source: 'user_messages'
}

export interface BaseEvaluationConfig {
    id: string
    name: string
    description?: string
    enabled: boolean
    status: EvaluationStatus
    status_reason: EvaluationStatusReason | null
    status_reason_detail: string | null
    output_type: EvaluationOutputType
    output_config: EvaluationOutputConfig
    conditions: EvaluationConditionSet[]
    /** What the evaluation runs on: each matching generation event, or the whole trace once. */
    target: EvaluationTarget
    /** Target-specific settings. For 'trace': {window_seconds}. Empty for 'generation'. */
    target_config: EvaluationTargetConfig
    model_configuration: ModelConfiguration | null
    total_runs: number
    last_run_at?: string
    created_at: string
    updated_at: string
    deleted?: boolean
}

export interface LLMJudgeEvaluation extends BaseEvaluationConfig {
    evaluation_type: 'llm_judge'
    output_type: 'boolean'
    evaluation_config: LLMJudgeEvaluationConfig
}

export interface HogEvaluation extends BaseEvaluationConfig {
    evaluation_type: 'hog'
    output_type: 'boolean'
    evaluation_config: HogEvaluationConfig
}

export interface SentimentEvaluation extends BaseEvaluationConfig {
    evaluation_type: 'sentiment'
    output_type: 'sentiment'
    evaluation_config: SentimentEvaluationConfig
    model_configuration: null
}

export type EvaluationConfig = LLMJudgeEvaluation | HogEvaluation | SentimentEvaluation

export interface EvaluationConditionSet {
    id: string
    // Optional because the backend serializer has `default=100` (not `required=True`), so legacy
    // condition rows stored in the JSONField before the field existed read back without the key.
    rollout_percentage?: number
    // Optional for the same reason: conditions live in a free-form JSONField and the inner shape
    // isn't validated, so legacy rows can come back without a `properties` key.
    properties?: AnyPropertyFilter[]
}

export interface EvaluationRun {
    id: string
    evaluation_id: string
    evaluation_name: string
    generation_id: string | null
    trace_id: string
    timestamp: string
    evaluation_type?: EvaluationType
    result_type?: EvaluationOutputType
    result: boolean | null
    sentiment_label?: string | null
    sentiment_score?: number | null
    applicable?: boolean
    reasoning: string
    status: 'completed' | 'failed' | 'running'
}

export interface HogTestResult {
    event_uuid: string
    trace_id?: string | null
    input_preview: string
    output_preview: string
    result: boolean | null
    reasoning: string
    error: string | null
}

export type EvaluationReportFrequency = 'scheduled' | 'every_n'

export interface EvaluationReportDeliveryTarget {
    type: 'email' | 'slack'
    value?: string
    integration_id?: number
    channel?: string
}

export interface EvaluationReport {
    id: string
    evaluation: string
    frequency: EvaluationReportFrequency
    /** RFC 5545 RRULE string (empty for every_n). */
    rrule: string
    /** Anchor datetime for rrule expansion (null for every_n). */
    starts_at: string | null
    /** IANA timezone for expanding rrule occurrences. */
    timezone_name: string
    next_delivery_date: string | null
    delivery_targets: EvaluationReportDeliveryTarget[]
    max_sample_size: number
    enabled: boolean
    deleted: boolean
    last_delivered_at: string | null
    /** Optional per-report custom guidance appended to the agent's system prompt. */
    report_prompt_guidance: string
    /** Number of new eval results that triggers a report (only for every_n frequency). */
    trigger_threshold: number | null
    /** Minimum minutes between count-triggered reports. */
    cooldown_minutes: number
    /** Maximum count-triggered report runs per calendar day (UTC). */
    daily_run_cap: number
    created_by: number | null
    created_at: string
}

/** A titled markdown section of the report (v2: agent-chosen title). */
export interface EvaluationReportSection {
    title: string
    content: string
}

/** A trace reference cited by the agent to ground a specific finding. */
export interface EvaluationReportCitation {
    generation_id: string
    trace_id: string
    reason: string
}

/** Structured metrics computed mechanically from ClickHouse (agent cannot fabricate). */
export interface EvaluationReportMetrics {
    total_runs: number
    pass_count: number
    fail_count: number
    na_count: number
    pass_rate: number
    period_start: string
    period_end: string
    previous_total_runs: number | null
    previous_pass_rate: number | null
}

/** Top-level report content stored in EvaluationReportRun.content. */
export interface EvaluationReportRunContent {
    title: string
    sections: EvaluationReportSection[]
    citations: EvaluationReportCitation[]
    metrics: EvaluationReportMetrics
}

export interface EvaluationReportRun {
    id: string
    report: string
    content: EvaluationReportRunContent
    /** Legacy mirror of content.metrics — populated by the store activity for backwards compat. */
    metadata: EvaluationReportMetrics
    period_start: string
    period_end: string
    delivery_status: 'pending' | 'delivered' | 'partial_failure' | 'failed'
    delivery_errors: string[]
    created_at: string
}

export type SentimentEvaluationRunsFilter = 'negative' | 'positive' | 'neutral' | 'all'
export type EvaluationSummaryFilter = 'pass' | 'fail' | 'na' | SentimentEvaluationRunsFilter

export interface EvaluationPattern {
    title: string
    description: string
    frequency: string
    example_generation_ids: string[]
}

export interface EvaluationSummaryStatistics {
    total_analyzed: number
    pass_count: number
    fail_count: number
    na_count: number
}

export interface EvaluationSummary {
    overall_assessment: string
    pass_patterns: EvaluationPattern[]
    fail_patterns: EvaluationPattern[]
    na_patterns: EvaluationPattern[]
    recommendations: string[]
    statistics: EvaluationSummaryStatistics
}
