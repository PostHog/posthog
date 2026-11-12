import type { OfflineScorerSummaryApi } from '../generated/api.schemas'

export function offlineUnscoredLabel(summary: OfflineScorerSummaryApi): string {
    return summary.scorer.calculation === 'composite'
        ? `${summary.not_requested_count} not requested`
        : `${summary.missing_result_count} missing`
}
