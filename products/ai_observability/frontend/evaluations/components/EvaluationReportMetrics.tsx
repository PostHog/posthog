import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { EvaluationReportStoredMetrics } from '../types'
import { EvaluationDrawerStat } from './EvaluationDrawerStat'
import { headlineChange, type ReportHeadline } from './reportHeadline'
import { isPassFailOutput, reportResultMetrics } from './reportMetrics'

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

const MAX_STATS = 4

/** The report's numbers as a row of stats: the headline rate, the result count, then each outcome. */
export function EvaluationReportMetrics({
    metrics,
    headline,
}: {
    metrics: EvaluationReportStoredMetrics
    headline: ReportHeadline | null
}): JSX.Element {
    const change = headline ? headlineChange(headline) : null
    // A share of all results beside the pass rate reads as a second, conflicting rate, so pass/fail leaves it out.
    const passFail = isPassFailOutput(metrics)
    const rule = passingRuleText(metrics)
    const stats: { label: string; value: string; detail?: React.ReactNode }[] = []
    if (headline) {
        stats.push({
            label: headline.label,
            value: `${headline.value.toFixed(1)}%`,
            detail: change ? (
                <span className={change.className}>
                    {`${change.change > 0 ? '▲' : '▼'} ${Math.abs(change.change).toFixed(1)}pp vs previous`}
                </span>
            ) : (
                'No change vs previous'
            ),
        })
    }
    if (metrics.total_runs != null) {
        stats.push({
            label: 'Results',
            value: humanFriendlyNumber(metrics.total_runs),
            detail:
                metrics.previous_total_runs != null
                    ? `${humanFriendlyNumber(metrics.previous_total_runs)} previously`
                    : 'In this period',
        })
    }
    for (const { label, count, rate } of reportResultMetrics(metrics)) {
        if (stats.length >= MAX_STATS) {
            break
        }
        if (count != null) {
            stats.push({
                label,
                value: humanFriendlyNumber(count),
                detail: !passFail && rate != null ? `${rate.toFixed(1)}% of results` : undefined,
            })
        }
    }

    return (
        <section className="flex flex-col gap-2">
            <div className="grid grid-cols-2 gap-2 @min-[36rem]:grid-cols-4">
                {stats.map((stat) => (
                    <EvaluationDrawerStat key={stat.label} label={stat.label} value={stat.value} detail={stat.detail} />
                ))}
            </div>
            {rule && <p className="mb-0 text-xs text-secondary">{rule}</p>}
        </section>
    )
}
