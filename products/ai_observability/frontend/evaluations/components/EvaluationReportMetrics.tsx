import type { EvaluationReportStoredMetrics } from '../types'
import { EvaluationDrawerStat } from './EvaluationDrawerStat'
import type { ReportHeadline } from './reportHeadline'
import { reportStats } from './reportStats'

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
    const rule = passingRuleText(metrics)
    return (
        <section className="flex flex-col gap-2">
            <div className="grid grid-cols-2 gap-2 @min-[36rem]:grid-cols-4">
                {reportStats(metrics, headline).map(({ label, value, detail, detailClassName }) => (
                    <EvaluationDrawerStat
                        key={label}
                        label={label}
                        value={value}
                        detail={detail && <span className={detailClassName}>{detail}</span>}
                    />
                ))}
            </div>
            {rule && <p className="mb-0 text-xs text-secondary">{rule}</p>}
        </section>
    )
}
