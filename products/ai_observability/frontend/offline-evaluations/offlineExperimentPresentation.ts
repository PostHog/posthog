import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { ExperimentScoreInputApi, OfflineHistoryPointApi } from '../generated/api.schemas'

const versionList = new Intl.ListFormat('en')

export function formatItemScorerVersions(input: ExperimentScoreInputApi): string {
    return versionList.format(input.sources.map((source) => `v${source.version}`))
}

export function explainMixedScorerVersions(input: ExperimentScoreInputApi): string {
    const versions = versionList.format(
        input.sources.filter((source) => source.successful_items > 0).map((source) => `v${source.version}`)
    )
    return `Items were scored with ${versions} of “${input.alias}”. This formula can use only one of those versions per run.`
}

export function offlineExperimentUrl(point: OfflineHistoryPointApi): string {
    const url = urls.aiObservabilityOfflineEvaluationExperiment(point.experiment.id)
    return point.summary
        ? combineUrl(url, {
              scorer_version_id: point.summary.scorer.id,
          }).url
        : url
}
