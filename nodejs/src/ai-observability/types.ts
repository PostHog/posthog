import { HogBytecode } from '../cdp/types'
import { PropertyFilter } from '../types'

export type EvaluationStatus = 'active' | 'paused' | 'error'
// Keep in sync with EvaluationStatusReason in products/ai_observability/backend/models/evaluations.py
export type EvaluationStatusReason =
    | 'provider_key_required'
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
export type EvaluationTarget = 'generation' | 'trace'

export interface Evaluation {
    id: string
    team_id: number
    name: string
    description?: string
    enabled: boolean
    status: EvaluationStatus
    status_reason?: EvaluationStatusReason
    evaluation_type: string
    evaluation_config: Record<string, any>
    output_type: string
    output_config: Record<string, any>
    conditions: EvaluationConditionSet[]
    target: EvaluationTarget
    // Target-specific settings keyed off `target`. Trace targets carry the aggregation window.
    target_config: { window_seconds?: number }
    provider_key_id?: string | null
    created_at: string
    updated_at: string
}

export interface EvaluationConditionSet {
    id: string
    rollout_percentage: number
    properties: PropertyFilter[]
    bytecode?: HogBytecode // Compiled on save in Python, embedded in JSON
    bytecode_error?: string
}

export type EvaluationInfo = Pick<Evaluation, 'id' | 'team_id'>

/** Shared interface for condition matching — used by both evaluations and taggers. */
export interface Matchable {
    enabled: boolean
    conditions: EvaluationConditionSet[]
}

export interface Tagger {
    id: string
    team_id: number
    name: string
    description?: string
    enabled: boolean
    tagger_type: string
    tagger_config: {
        prompt: string
        tags: { name: string; description?: string }[]
        min_tags: number
        max_tags: number | null
    }
    conditions: EvaluationConditionSet[]
    provider_key_id?: string | null
    created_at: string
    updated_at: string
}

export type TaggerInfo = Pick<Tagger, 'id' | 'team_id'>
