import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { OfflineHistoryPointApi } from '../generated/api.schemas'

export function offlineExperimentUrl(point: OfflineHistoryPointApi): string {
    return combineUrl(urls.aiObservabilityOfflineEvaluationExperiment(point.experiment.id), {
        scorer_version_id: point.summary.scorer.id,
    }).url
}
