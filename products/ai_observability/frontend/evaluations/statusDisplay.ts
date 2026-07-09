import { EvaluationStatusReason } from './types'

const REASON_LABELS: Record<EvaluationStatusReason, string> = {
    provider_key_required: 'No provider API key configured',
    trial_limit_reached: 'Trial evaluation limit reached',
    model_not_allowed: 'Model not available on the trial plan',
    provider_key_deleted: 'Provider API key was deleted',
    no_default_model: 'No default model available for the selected provider',
    provider_key_invalid: 'Provider API key is invalid',
    provider_key_permission_denied: 'Provider API key lacks model access',
    provider_key_quota_exceeded: 'Provider API key quota exceeded',
    provider_key_rate_limited: 'Provider API key is rate limited',
    model_not_found: 'Model not found',
    hog_error: 'Hog evaluation code failed',
}

const PROVIDER_KEY_REASONS = new Set<EvaluationStatusReason>([
    'provider_key_deleted',
    'provider_key_invalid',
    'provider_key_permission_denied',
    'provider_key_quota_exceeded',
    'provider_key_rate_limited',
])

export function statusReasonLabel(reason: EvaluationStatusReason | null | undefined): string {
    if (!reason) {
        return 'Disabled by the system'
    }
    return REASON_LABELS[reason] ?? 'Disabled by the system'
}

export function statusReasonRecoveryLabel(reason: EvaluationStatusReason | null | undefined): string {
    if (reason === 'provider_key_required' || reason === 'trial_limit_reached') {
        return 'Add a provider API key in settings, then re-enable the evaluation to resume running.'
    }
    if (reason === 'model_not_allowed') {
        return 'Choose a supported model or add a provider API key in settings, then re-enable the evaluation to resume running.'
    }
    if (reason === 'no_default_model' || reason === 'model_not_found') {
        return 'Choose an available model, then re-enable the evaluation to resume running.'
    }
    if (reason === 'hog_error') {
        return 'Fix the Hog code, then re-enable the evaluation to resume running.'
    }
    if (reason && PROVIDER_KEY_REASONS.has(reason)) {
        return 'Fix or replace the provider API key in settings, then re-enable the evaluation to resume running.'
    }
    return 'Fix the configuration, then re-enable the evaluation to resume running.'
}
