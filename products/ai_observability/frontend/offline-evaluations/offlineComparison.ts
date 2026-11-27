import { combineUrl } from 'kea-router'

import { isUUIDLike } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import type { ExperimentScoreApi, OfflineExperimentReadApi, OfflineScorerSummaryApi } from '../generated/api.schemas'
import { offlineNumericPassingRule } from './offlineScoreInterpretation'

export const MAX_COMPARISON_RUNS = 50

export function comparisonIds(value: unknown): string[] {
    if (typeof value !== 'string') {
        return []
    }
    const ids = [...new Set(value.toLowerCase().split(','))]
    return ids.length >= 2 && ids.length <= MAX_COMPARISON_RUNS && ids.every(isUUIDLike) ? ids : []
}

export function comparisonUrl(ids: readonly (string | number)[], search: Record<string, unknown>): string {
    return combineUrl(urls.aiObservabilityOfflineEvaluations(), {
        ...search,
        compare: ids.length ? ids.join(',') : undefined,
        compare_scores: ids.length && search.compare_scores === 'shared' ? 'shared' : undefined,
    }).url
}

export interface ComparisonRun {
    experiment: OfflineExperimentReadApi
    summaries: OfflineScorerSummaryApi[]
}

type ItemScoreRow = {
    kind: 'item'
    id: string
    scorer: OfflineScorerSummaryApi['scorer']
    scores: Map<string, OfflineScorerSummaryApi>
}

type ExperimentScoreRow = {
    kind: 'experiment'
    id: string
    scorer: ExperimentScoreApi
    scores: Map<string, ExperimentScoreApi>
}

export type ComparisonScoreRow = ItemScoreRow | ExperimentScoreRow

export function comparisonScoreRows(runs: ComparisonRun[]): ComparisonScoreRow[] {
    const items = new Map<string, ItemScoreRow>()
    const experiments = new Map<string, ExperimentScoreRow>()
    for (const { experiment, summaries } of runs) {
        const overall = experiment.experiment_score
        if (overall) {
            const id = overall.scorer_version_id
            const row = experiments.get(id) ?? { kind: 'experiment', id, scorer: overall, scores: new Map() }
            row.scores.set(experiment.id, overall)
            experiments.set(id, row)
        }
        for (const summary of summaries) {
            const { scorer } = summary
            const row = items.get(scorer.id) ?? { kind: 'item', id: scorer.id, scorer, scores: new Map() }
            row.scores.set(experiment.id, summary)
            items.set(scorer.id, row)
        }
    }
    return [...experiments.values(), ...items.values()].sort(
        (a, b) =>
            a.kind.localeCompare(b.kind) ||
            b.scores.size - a.scores.size ||
            a.scorer.name.localeCompare(b.scorer.name) ||
            a.scorer.version - b.scorer.version
    )
}

export function aggregateDifference(
    current: OfflineScorerSummaryApi,
    baseline?: OfflineScorerSummaryApi
): { label: string; outcome: 'better' | 'worse' | 'neutral' } | null {
    if (
        !baseline ||
        current.scorer.id !== baseline.scorer.id ||
        !current.status_counts.ok ||
        !baseline.status_counts.ok
    ) {
        return null
    }
    const rate = current.scorer.kind === 'boolean'
    const left = rate ? current.pass_rate : current.mean
    const right = rate ? baseline.pass_rate : baseline.mean
    if (left === null || right === null) {
        return null
    }
    const delta = (left - right) * (rate ? 100 : 1)
    if (delta === 0) {
        return { label: 'Unchanged', outcome: 'neutral' }
    }
    const magnitude = Math.abs(delta).toLocaleString(undefined, { maximumSignificantDigits: 3 })
    const label = `${delta > 0 ? '+' : '−'}${magnitude}${rate ? ' pp' : ''}`
    const operator = rate ? 'gte' : offlineNumericPassingRule(current.scorer)?.operator
    if (!operator) {
        return { label, outcome: 'neutral' }
    }
    return { label, outcome: (operator === 'gte' ? delta > 0 : delta < 0) ? 'better' : 'worse' }
}
