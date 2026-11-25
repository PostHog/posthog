import { LemonTag } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import type { ExperimentScoreApi, ExperimentScorePreviewApi } from '../generated/api.schemas'
import { getCategoricalConfig, getNumericConfig } from '../scoreDefinitions/scoreDefinitionConfigUtils'
import { ScorerLabel } from '../scoreDefinitions/ScorerLabel'
import { explainMixedScorerVersions } from './offlineExperimentPresentation'
import { boundedScorePercent, offlineNumericPassingRule, offlineScorePasses } from './offlineScoreInterpretation'
import { formatOfflineNumericScore, formatOfflinePercentage } from './offlineScoreTrends'

const statusLabels: Record<string, string> = {
    mixed_versions: 'Not calculated',
    missing_input: 'Missing scorer results',
    no_successful_items: 'No successful items',
    unavailable_statistic: 'Statistic unavailable for this version',
    overlapping_items: 'Multiple versions scored the same item',
    formula_error: 'Formula output is outside its configuration',
    pending: 'Waiting for completion',
    failed: 'Experiment failed',
}

export function experimentScoreLabel(score: ExperimentScorePreviewApi | ExperimentScoreApi): string {
    if (score.status !== 'ok' || score.value === null) {
        return statusLabels[score.status] ?? 'Unavailable'
    }
    if (Array.isArray(score.value)) {
        const options = 'config' in score ? getCategoricalConfig(score.config).options : []
        return (
            score.value.map((key) => options.find((option) => option.key === key)?.label ?? key).join(', ') ||
            'No categories'
        )
    }
    if (typeof score.value === 'number') {
        const rounded = Number(score.value.toFixed(2))
        if (
            (rounded === 0 && score.value !== 0) ||
            ('config' in score && offlineScorePasses(score.value, score) !== offlineScorePasses(rounded, score))
        ) {
            return formatOfflineNumericScore(score.value, 'config' in score ? offlineNumericPassingRule(score) : null)
        }
        return rounded.toLocaleString(undefined, { maximumFractionDigits: 2 })
    }
    return score.value ? 'True' : 'False'
}

export function ExperimentScoreResult({
    score,
    historyUrl,
}: {
    score: ExperimentScorePreviewApi | ExperimentScoreApi
    historyUrl?: string
}): JSX.Element {
    const scorer = 'scorer_version_id' in score ? score : null
    const numeric = scorer?.kind === 'numeric' ? getNumericConfig(scorer.config) : null
    const percent = numeric && typeof score.value === 'number' ? boundedScorePercent(score.value, numeric) : null
    const passes = scorer && score.status === 'ok' ? offlineScorePasses(score.value, scorer) : null
    const mixedInputs =
        score.status === 'mixed_versions' ? score.inputs.filter((input) => input.status === 'mixed_versions') : []
    return (
        <section
            className={`min-w-0 bg-surface-primary px-4 py-4 @container/experiment-score ${scorer ? 'rounded-t-lg border-b' : 'rounded-lg border'}`}
        >
            <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3">
                <div className="min-w-0">
                    <h3 className="mb-1 text-sm font-medium text-muted">
                        {scorer ? 'Experiment score' : 'Preview score'}
                    </h3>
                    {scorer && historyUrl && (
                        <ScorerLabel
                            scorer={scorer}
                            historyLink={{ to: historyUrl, 'data-attr': 'aio-experiment-score-history' }}
                        />
                    )}
                </div>
                <div className="flex flex-wrap items-center justify-end gap-3">
                    {percent !== null && (
                        <LemonProgress
                            className="hidden @min-[38rem]/experiment-score:block @min-[38rem]/experiment-score:w-32 @min-[54rem]/experiment-score:w-52"
                            role="meter"
                            aria-label="Experiment score"
                            aria-valuemin={numeric?.min ?? undefined}
                            aria-valuemax={numeric?.max ?? undefined}
                            aria-valuenow={typeof score.value === 'number' ? score.value : undefined}
                            percent={percent}
                            bgColor="var(--color-bg-fill-tertiary)"
                            strokeColor={passes === null ? undefined : passes ? 'var(--success)' : 'var(--danger)'}
                        />
                    )}
                    {passes !== null && (
                        <LemonTag type={passes ? 'success' : 'danger'}>{passes ? 'Passed' : 'Failed'}</LemonTag>
                    )}
                    <div className="flex flex-wrap items-baseline gap-1">
                        <strong
                            className={
                                score.status === 'ok' ? 'text-3xl font-semibold tabular-nums' : 'text-lg font-semibold'
                            }
                        >
                            {experimentScoreLabel(score)}
                        </strong>
                        {score.status === 'ok' && numeric?.min === 0 && numeric.max != null && (
                            <span className="text-muted">/ {numeric.max}</span>
                        )}
                    </div>
                </div>
            </div>
            {mixedInputs.map((input) => (
                <p key={input.alias} className="mt-2 mb-0 text-sm">
                    {explainMixedScorerVersions(input)}
                </p>
            ))}
            {score.inputs.length > 0 && (
                <details className="mt-3 border-t pt-2 text-sm">
                    <summary className="cursor-pointer text-muted w-fit" data-attr="aio-experiment-score-breakdown">
                        Experiment score breakdown
                    </summary>
                    <ul className="mt-2 mb-0 list-none p-0 space-y-2">
                        {score.inputs.map((input) => (
                            <li key={input.alias} className="flex flex-wrap items-baseline gap-x-3">
                                <span>
                                    <code>{input.alias}</code> · {input.statistic.replaceAll('_', ' ')}
                                </span>
                                {input.status !== 'ok' && <span>{statusLabels[input.status]}</span>}
                                {input.sources.map((source) => (
                                    <span key={source.version_id} className="text-muted">
                                        v{source.version} ·{' '}
                                        {source.value === null
                                            ? '—'
                                            : input.statistic.endsWith('_rate')
                                              ? formatOfflinePercentage(source.value)
                                              : formatOfflineNumericScore(source.value)}{' '}
                                        ({source.successful_items} scored)
                                    </span>
                                ))}
                            </li>
                        ))}
                    </ul>
                </details>
            )}
        </section>
    )
}
