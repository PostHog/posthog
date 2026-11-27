import { LemonButton, LemonDropdown, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { getNumericConfig } from '../scoreDefinitions/scoreDefinitionConfigUtils'
import { boundedScorePercent, offlineScorePasses } from './offlineScoreInterpretation'
import {
    formatOfflinePercentage,
    formatOfflineScore,
    offlineScoreMetricLabel,
    offlineScorePassingRuleLabel,
    type OfflineScoreSummary,
} from './offlineScoreTrends'

function SummaryMetric({
    label,
    value,
    percent,
    color,
    title,
    passed,
}: {
    label?: string
    value: string
    percent: number | null
    color?: string
    title: string
    passed?: boolean | null
}): JSX.Element {
    return (
        <Tooltip title={title} className="whitespace-pre-line">
            <div
                className="flex w-fit max-w-full flex-wrap items-center gap-x-2 gap-y-0.5"
                tabIndex={0}
                aria-description={title}
            >
                {percent !== null && (
                    <div className="inline-flex w-14 shrink-0 items-center" aria-hidden="true">
                        <LemonProgress percent={percent} bgColor="var(--color-bg-fill-tertiary)" strokeColor={color} />
                    </div>
                )}
                <strong className="self-baseline tabular-nums font-semibold">
                    {value}
                    {passed != null && <span className="sr-only">{passed ? ' Passed' : ' Failed'}</span>}
                </strong>
                {label && <span className="text-xs text-muted break-words min-w-0">{label}</span>}
            </div>
        </Tooltip>
    )
}

export function OfflineSummaryMetrics({
    summary,
    compact = false,
    showMetricLabel = true,
}: {
    summary: OfflineScoreSummary
    compact?: boolean
    showMetricLabel?: boolean
}): JSX.Element {
    const { scorer, mean, pass_count, fail_count, pass_rate, categories, status_counts } = summary
    if (!status_counts.ok) {
        return <span className="text-sm text-muted">No successful results</span>
    }

    const numeric = scorer.kind === 'numeric'
    const passed = numeric ? offlineScorePasses(mean, scorer) : null
    const ruleLabel = offlineScorePassingRuleLabel(scorer)
    const categoryMetric = (category: OfflineScoreSummary['categories'][number]): JSX.Element => (
        <SummaryMetric
            key={category.key}
            label={category.label}
            value={category.rate === null ? '—' : formatOfflinePercentage(category.rate)}
            percent={category.rate === null ? null : category.rate * 100}
            title={[`${category.count} of ${status_counts.ok} scored items include “${category.label}”`, ruleLabel]
                .filter(Boolean)
                .join('\n')}
        />
    )
    if (scorer.kind === 'categorical') {
        if (!categories.length) {
            return <span className="text-xs text-muted">No categories</span>
        }
        if (compact) {
            const topCategory = categories.reduce((top, category) =>
                (category.rate ?? -1) > (top.rate ?? -1) ? category : top
            )
            return (
                <div className="flex min-w-0 flex-wrap items-center gap-1">
                    {categoryMetric(topCategory)}
                    {categories.length > 1 && (
                        <LemonDropdown
                            placement="bottom-end"
                            closeOnClickInside={false}
                            overlay={
                                <div
                                    className="max-h-64 max-w-xs space-y-2 overflow-y-auto p-2"
                                    aria-label="Category rates"
                                    role="region"
                                >
                                    {categories.map(categoryMetric)}
                                </div>
                            }
                        >
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                data-attr="offline-score-category-rates"
                                aria-label={`Show all ${categories.length} category rates`}
                            >
                                +{categories.length - 1} {categories.length === 2 ? 'other' : 'others'}
                            </LemonButton>
                        </LemonDropdown>
                    )}
                </div>
            )
        }
        return (
            <>
                {categories.slice(0, 3).map(categoryMetric)}
                {categories.length > 3 && (
                    <details>
                        <summary
                            className="cursor-pointer text-xs text-muted"
                            data-attr="offline-score-more-categories"
                        >{`${categories.length - 3} more ${categories.length === 4 ? 'category' : 'categories'}`}</summary>
                        <div className="mt-1 space-y-1">{categories.slice(3).map(categoryMetric)}</div>
                    </details>
                )}
            </>
        )
    }
    const passRateDetail =
        pass_count != null && fail_count != null && pass_rate != null
            ? `${pass_count} of ${pass_count + fail_count} scored items passed (${formatOfflinePercentage(pass_rate)})`
            : null
    return (
        <SummaryMetric
            label={showMetricLabel ? offlineScoreMetricLabel(scorer) : undefined}
            passed={passed}
            value={formatOfflineScore(summary)}
            percent={
                numeric
                    ? boundedScorePercent(mean, getNumericConfig(scorer.config))
                    : pass_rate == null
                      ? null
                      : pass_rate * 100
            }
            color={passed === false ? 'var(--danger)' : passed === true || !numeric ? 'var(--success)' : undefined}
            title={[
                ruleLabel ?? 'No passing rule',
                numeric && mean !== null && `Mean ${mean}${passed === null ? '' : passed ? ' · Passed' : ' · Failed'}`,
                passRateDetail,
            ]
                .filter(Boolean)
                .join('\n')}
        />
    )
}

export function OfflineScoreCounts({
    summary,
    showPassRate = true,
}: {
    summary: OfflineScoreSummary
    showPassRate?: boolean
}): JSX.Element | null {
    const { scorer, pass_rate, pass_count, fail_count } = summary
    return summary.status_counts.ok > 0 && pass_count != null && fail_count != null ? (
        <div className="flex flex-wrap gap-x-2 text-xs text-muted tabular-nums">
            {showPassRate && scorer.kind !== 'boolean' && pass_rate != null && (
                <span>{`${formatOfflinePercentage(pass_rate)} pass rate`}</span>
            )}
            <span>{`${pass_count} passed · ${fail_count} failed`}</span>
        </div>
    ) : null
}

export function OfflineScoreSummaryDisplay({ summary }: { summary: OfflineScoreSummary }): JSX.Element {
    return (
        <div className="min-w-0 flex flex-col gap-1">
            <OfflineSummaryMetrics summary={summary} />
            <OfflineScoreCounts summary={summary} />
        </div>
    )
}
