import { EvaluationStatusReason } from './types'

const REASON_LABELS: Record<EvaluationStatusReason, string> = {
    trial_limit_reached: 'Trial evaluation limit reached',
    model_not_allowed: 'Model not available on the trial plan',
    provider_key_deleted: 'Provider API key was deleted',
}

export function statusReasonLabel(reason: EvaluationStatusReason | null | undefined): string {
    if (!reason) {
        return 'Disabled by the system'
    }
    return REASON_LABELS[reason] ?? 'Disabled by the system'
}
