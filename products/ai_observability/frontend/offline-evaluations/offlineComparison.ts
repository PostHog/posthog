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

export interface ScoreDifference {
    label: string
    outcome: 'better' | 'worse' | 'neutral'
}

function numericDifference(
    current: number | null,
    baseline: number | null,
    operator: 'gte' | 'lte' | undefined,
    percentagePoints = false
): ScoreDifference | null {
    if (current === null || baseline === null) {
        return null
    }
    const delta = (current - baseline) * (percentagePoints ? 100 : 1)
    if (delta === 0) {
        return { label: 'Unchanged', outcome: 'neutral' }
    }
    const magnitude = Math.abs(delta).toLocaleString(undefined, { maximumSignificantDigits: 3 })
    const label = `${delta > 0 ? '+' : '−'}${magnitude}${percentagePoints ? ' pp' : ''}`
    if (!operator) {
        return { label, outcome: 'neutral' }
    }
    const outcome = (operator === 'gte' ? delta > 0 : delta < 0) ? 'better' : 'worse'
    return { label: `${label} ${outcome}`, outcome }
}

export function aggregateDifference(
    current: OfflineScorerSummaryApi,
    baseline?: OfflineScorerSummaryApi
): ScoreDifference | null {
    if (
        !baseline ||
        current.scorer.id !== baseline.scorer.id ||
        !current.status_counts.ok ||
        !baseline.status_counts.ok
    ) {
        return null
    }
    return current.scorer.kind === 'numeric'
        ? numericDifference(current.mean, baseline.mean, offlineNumericPassingRule(current.scorer)?.operator)
        : numericDifference(current.pass_rate, baseline.pass_rate, 'gte', true)
}

export function experimentScoreDifference(
    current: ExperimentScoreApi,
    baseline?: ExperimentScoreApi
): ScoreDifference | null {
    if (
        !baseline ||
        current.scorer_version_id !== baseline.scorer_version_id ||
        current.status !== 'ok' ||
        baseline.status !== 'ok' ||
        current.value === null ||
        baseline.value === null
    ) {
        return null
    }
    if (current.kind === 'numeric') {
        const rule = offlineNumericPassingRule(current)
        return rule && typeof current.value === 'number' && typeof baseline.value === 'number'
            ? numericDifference(current.value, baseline.value, rule.operator)
            : null
    }
    if (current.passed === null || baseline.passed === null) {
        return null
    }
    if (current.passed === baseline.passed) {
        return { label: current.passed ? 'Still passes' : 'Still fails', outcome: 'neutral' }
    }
    return current.passed ? { label: 'Now passes', outcome: 'better' } : { label: 'Now fails', outcome: 'worse' }
}
