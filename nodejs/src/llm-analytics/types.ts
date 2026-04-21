import { HogBytecode } from '../cdp/types'
import { PropertyFilter } from '../types'

export type EvaluationStatus = 'active' | 'paused' | 'error'
export type EvaluationStatusReason = 'trial_limit_reached' | 'model_not_allowed' | 'provider_key_deleted'

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
