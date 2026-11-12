import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { EvaluationReportStoredMetrics } from '../types'
import { headlineChange, type ReportHeadline } from './reportHeadline'
import { isPassFailOutput, reportResultMetrics, reportResultSegments } from './reportMetrics'
import { ReportResultBar, resultTone } from './ReportResultBar'

function passingRuleText(metrics: EvaluationReportStoredMetrics): string | null {
    const rule =
        metrics.output_config && 'passing_rule' in metrics.output_config ? metrics.output_config.passing_rule : null
    if (metrics.output_type === 'numeric' && rule && 'threshold' in rule) {
        return `Passing rule used for this report: score ${rule.operator === 'gte' ? '≥' : '≤'} ${rule.threshold}`
    }
    if (metrics.output_type === 'categorical' && rule && 'categories' in rule) {
        const labels = rule.categories
            .map((key) => metrics.output_config?.options?.find((option) => option.key === key)?.label ?? key)
            .join(', ')
        return `Passing categories used for this report: ${labels || 'None'}. Every returned category must pass.`
    }
    return null
}

export function EvaluationReportMetrics({
    metrics,
    headline,
}: {
    metrics: EvaluationReportStoredMetrics
    headline: ReportHeadline | null
}): JSX.Element {
    const passFail = isPassFailOutput(metrics)
    const change = headline ? headlineChange(headline) : null
    const results = reportResultMetrics(metrics).filter(
        ({ count, rate }) => count != null || (!passFail && rate != null)
    )
    const rule = passingRuleText(metrics)

    return (
        <section className="flex flex-col gap-3 rounded border bg-surface-primary p-4">
            {headline && (
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="text-3xl font-semibold leading-none tabular-nums">{`${headline.value.toFixed(1)}%`}</span>
                    <span className="text-sm text-secondary">{headline.label.toLowerCase()}</span>
                    {change && (
                        <span className={cn('text-sm font-medium tabular-nums', change.className)}>
                            {`${change.change > 0 ? '▲' : '▼'} ${Math.abs(change.change).toFixed(1)}pp vs previous report`}
                        </span>
                    )}
                </div>
            )}
            <ReportResultBar segments={reportResultSegments(metrics)} className="h-2" />
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                {results.map(({ key, label, count, rate }) => (
                    <span key={key} className="flex items-center gap-1.5">
                        <span className={cn('size-2 rounded-full', resultTone(key))} />
                        <span className="text-secondary">{label}</span>
                        <span className="font-semibold tabular-nums">{count ?? '–'}</span>
                        {!passFail && rate != null && <span className="text-secondary">{`(${rate.toFixed(1)}%)`}</span>}
                    </span>
                ))}
                {metrics.total_runs != null && (
                    <span className="ml-auto text-secondary">
                        {`${humanFriendlyNumber(metrics.total_runs)} results`}
                        {metrics.previous_total_runs != null &&
                            ` · ${humanFriendlyNumber(metrics.previous_total_runs)} in the previous report`}
                    </span>
                )}
            </div>
            {rule && <p className="mb-0 text-xs text-secondary">{rule}</p>}
        </section>
    )
}
