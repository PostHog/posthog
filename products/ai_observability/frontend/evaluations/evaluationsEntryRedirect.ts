import { combineUrl } from 'kea-router'

import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { scorerFiltersFromSearchParams } from '../scoreDefinitions/scoreDefinitionNavigation'

export function getEvaluationsEntryRedirect(searchParams: Record<string, unknown>): string | null {
    if (searchParams.tab === 'scorers') {
        return combineUrl(urls.aiObservabilityScorers(), scorerFiltersFromSearchParams(searchParams)).url
    }
    if (searchParams.tab === 'offline' || searchParams.tab === 'offline-evals') {
        return typeof searchParams.experiment === 'string'
            ? urls.aiObservabilityOfflineEvaluationExperiment(searchParams.experiment)
            : urls.aiObservabilityOfflineEvaluations()
    }
    if (searchParams.tab === 'settings') {
        return urls.settings('project-ai-observability', 'ai-observability-byok')
    }
    if (getProductAccessDisabledReason({ sceneKey: Scene.AIObservabilityEvaluation })) {
        return urls.aiObservabilityScorers()
    }
    return null
}
