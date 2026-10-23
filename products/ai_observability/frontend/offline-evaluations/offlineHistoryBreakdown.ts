import type { AiObservabilityOfflineScorersHistoryListParams, OfflineHistoryPointApi } from '../generated/api.schemas'
import { offlineRunSourceLabel } from './offlineOverviewState'

export type OfflineHistoryBreakdown = NonNullable<AiObservabilityOfflineScorersHistoryListParams['breakdown']>

export const OFFLINE_HISTORY_BREAKDOWN_LABELS: Record<OfflineHistoryBreakdown, string> = {
    model_version: 'Model',
    prompt_version: 'Prompt version',
    application_version: 'Application version',
    suite_key: 'Suite',
    run_source: 'Run source',
}

export function offlineBreakdownValueLabel(
    value: string | null | undefined,
    breakdown: OfflineHistoryBreakdown
): string {
    if (value == null) {
        return 'Not specified'
    }
    return breakdown === 'run_source' ? offlineRunSourceLabel(value) : value
}

export function offlineHistoryPointKey(point: OfflineHistoryPointApi): string {
    return JSON.stringify([point.experiment.id, point.summary.scorer.id, point.breakdown_value ?? null])
}
