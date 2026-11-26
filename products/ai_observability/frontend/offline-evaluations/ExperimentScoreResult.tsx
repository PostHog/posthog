import { IconCheck, IconInfo, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'

import type { ExperimentScoreApi, ExperimentScorePreviewApi, OfflineScorerSummaryApi } from '../generated/api.schemas'
import {
    getBooleanConfig,
    getCategoricalConfig,
    getNumericConfig,
} from '../scoreDefinitions/scoreDefinitionConfigUtils'
import { ScorerLabel } from '../scoreDefinitions/ScorerLabel'
import { explainMixedScorerVersions } from './offlineExperimentPresentation'
import { boundedScorePercent, offlineNumericPassingRule, offlineScorePasses } from './offlineScoreInterpretation'
import { formatOfflineNumericScore, formatOfflinePercentage } from './offlineScoreTrends'

const statusLabels = {
    mixed_versions: 'Not calculated',
    missing_input: 'Missing scorer results',
    no_successful_items: 'No successful items',
    unavailable_statistic: 'Statistic unavailable for this version',
    overlapping_items: 'Multiple versions scored the same item',
    formula_error: 'The formula couldn’t produce a valid score for this run',
    pending: 'Waiting for completion',
    failed: 'Experiment failed',
} satisfies Record<Exclude<ExperimentScorePreviewApi['status'], 'ok'>, string>

export function experimentScoreLabel(score: ExperimentScorePreviewApi, exact = false): string {
    if (score.status !== 'ok') {
        if (score.status === 'mixed_versions') {
            return statusLabels.mixed_versions
        }
        const aliases = score.inputs.filter((input) => input.status === score.status).map((input) => input.alias)
        return [statusLabels[score.status], aliases.join(', ')].filter(Boolean).join(' · ')
    }
    if (score.value === null) {
        return 'Unavailable'
    }
    if (Array.isArray(score.value)) {
        const options = getCategoricalConfig(score.config).options
        return (
            score.value.map((key) => options.find((option) => option.key === key)?.label ?? key).join(', ') ||
            'No categories'
        )
    }
    if (typeof score.value === 'number') {
        if (exact) {
            return String(score.value)
        }
        const rounded = Number(score.value.toFixed(2))
        if ((rounded === 0 && score.value !== 0) || score.passed !== offlineScorePasses(rounded, score)) {
            return formatOfflineNumericScore(score.value, offlineNumericPassingRule(score))
        }
        return rounded.toLocaleString(undefined, { maximumFractionDigits: 2 })
    }
    const config = getBooleanConfig(score.config)
    return score.value ? config.true_label || 'True' : config.false_label || 'False'
}

export function ExperimentScoreResult({
    score,
    historyUrl,
    itemSummaries = [],
}: {
    score: ExperimentScorePreviewApi | ExperimentScoreApi
    historyUrl?: string
    itemSummaries?: OfflineScorerSummaryApi[]
}): JSX.Element {
    const scorer = 'scorer_version_id' in score ? score : null
    const numeric = score.kind === 'numeric' ? getNumericConfig(score.config) : null
    const percent = numeric && typeof score.value === 'number' ? boundedScorePercent(score.value, numeric) : null
    const passes = score.passed
    const mixedInputs =
        score.status === 'mixed_versions' ? score.inputs.filter((input) => input.status === 'mixed_versions') : []
    const scoreHelp = mixedInputs.length ? (
        <div className="space-y-2">
            {mixedInputs.map((input) => {
                const scorer = itemSummaries.find(({ scorer }) =>
                    input.sources.some((source) => source.version_id === scorer.id)
                )?.scorer
                return (
                    <div key={input.alias}>{explainMixedScorerVersions(input, scorer?.short_name || scorer?.name)}</div>
                )
            })}
        </div>
    ) : passes === null ? undefined : passes ? (
        'Passed'
    ) : (
        'Failed'
    )
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
                    <div className="flex flex-wrap items-baseline gap-1">
                        <Tooltip title={scoreHelp} openOnClick={mixedInputs.length > 0}>
                            <strong
                                className={cn(
                                    'inline-flex items-center gap-1 font-semibold',
                                    score.status === 'ok' ? 'text-3xl tabular-nums' : 'text-lg',
                                    passes === true && 'text-success',
                                    passes === false && 'text-danger'
                                )}
                                tabIndex={scoreHelp ? 0 : undefined}
                            >
                                {passes === true && <IconCheck className="text-xl" role="img" aria-label="Passed" />}
                                {passes === false && <IconX className="text-xl" role="img" aria-label="Failed" />}
                                {experimentScoreLabel(score)}
                                {mixedInputs.length > 0 && (
                                    <IconInfo className="text-muted shrink-0" aria-hidden="true" />
                                )}
                            </strong>
                        </Tooltip>
                        {score.status === 'ok' && numeric?.min === 0 && numeric.max != null && (
                            <span className="text-muted">/ {numeric.max}</span>
                        )}
                    </div>
                </div>
            </div>
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
