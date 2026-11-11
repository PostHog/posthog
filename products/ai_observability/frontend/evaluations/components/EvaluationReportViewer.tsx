import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type {
    EvaluationReportCitation,
    EvaluationOutputType,
    EvaluationReportRun,
    EvaluationReportSection,
    EvaluationReportStoredMetrics,
} from '../types'
import { EvaluationReportCitations } from './EvaluationReportCitations'
import { EvaluationReportPeriodChart } from './EvaluationReportPeriodChart'
import { linkifyCitations } from './reportCitationLinks'
import { ReportDeliveryTag } from './ReportDeliveryTag'

// Strip a leading markdown heading line if it matches the section title.
// The agent sometimes prefixes each section's content with its own heading,
// which duplicates the heading the renderer emits separately.
//
// Implemented as line-by-line string ops (no regex) — ATX headings are a
// well-defined subset of CommonMark: up to 3 leading spaces, then 1-6 `#`,
// then at least one space/tab, then the title text.
function stripRedundantLeadingHeading(content: string, sectionTitle: string): string {
    if (!sectionTitle.trim()) {
        return content
    }
    const lines = content.split('\n')
    if (lines.length === 0) {
        return content
    }
    const first = lines[0].trimStart()
    let hashCount = 0
    while (hashCount < 6 && first[hashCount] === '#') {
        hashCount++
    }
    if (hashCount === 0) {
        return content
    }
    const after = first[hashCount]
    if (after !== ' ' && after !== '\t') {
        return content
    }
    const headingText = first
        .slice(hashCount + 1)
        .trim()
        .toLowerCase()
    if (!headingText.startsWith(sectionTitle.toLowerCase())) {
        return content
    }
    // Drop the heading line plus any blank lines that followed it.
    let startIdx = 1
    while (startIdx < lines.length && lines[startIdx].trim() === '') {
        startIdx++
    }
    return lines.slice(startIdx).join('\n')
}

export function ReportSectionContent({
    section,
    citations,
}: {
    section: EvaluationReportSection
    citations: EvaluationReportCitation[]
}): JSX.Element {
    const markdown = linkifyCitations(
        stripRedundantLeadingHeading(section.content ?? '', section.title ?? ''),
        citations
    )
    // A model writes reports from trace content, so an injected image would call an outside server for each viewer.
    return (
        <LemonMarkdown lowKeyHeadings disableImages className="text-sm">
            {markdown}
        </LemonMarkdown>
    )
}

const RESULT_ORDER: Record<EvaluationOutputType, string[]> = {
    boolean: ['pass', 'fail', 'na'],
    numeric: ['pass', 'fail', 'na'],
    categorical: ['pass', 'fail', 'na'],
    sentiment: ['positive', 'neutral', 'negative'],
}

const PERIOD_FORMAT = { formatDate: 'MMM D', formatTime: 'HH:mm' }

const METRICS_UNAVAILABLE_MESSAGE =
    'Metrics could not be calculated for this period because evaluation data was temporarily unavailable. This does not mean that no evaluations ran.'

interface EvaluationReportResultMetric {
    key: string
    label: string
    count?: number
    rate?: number
    previousRate?: number
}

function formatResultLabel(result: string): string {
    if (result.toLowerCase() === 'na') {
        return 'N/A'
    }
    const label = result.split('_').join(' ')
    return label.length > 0 ? `${label[0].toUpperCase()}${label.slice(1)}` : result
}

function formatResultRate(rate: number | null | undefined, fractionDigits = 2): string {
    if (rate == null) {
        return '–'
    }
    return `${rate.toFixed(fractionDigits)}%`
}

function getResultMetrics(metrics: EvaluationReportStoredMetrics): EvaluationReportResultMetric[] {
    const resultCounts = metrics.result_counts ?? {}
    const totalResults = Object.values(resultCounts).reduce((total, count) => total + count, 0)
    const calculatedResultRates: Record<string, number> = {}
    if (totalResults > 0) {
        for (const [key, count] of Object.entries(resultCounts)) {
            calculatedResultRates[key] = (count / totalResults) * 100
        }
    }
    const genericResultRates = metrics.result_rates ?? {}
    const resultRates = Object.keys(genericResultRates).length > 0 ? genericResultRates : calculatedResultRates
    const previousResultRates = metrics.previous_result_rates
    const resultKeys = new Set([...Object.keys(resultCounts), ...Object.keys(resultRates)])
    const configuredOrder = RESULT_ORDER[metrics.output_type ?? 'boolean'] ?? []
    const orderedKeys = [...configuredOrder.filter((key) => resultKeys.delete(key)), ...Array.from(resultKeys).sort()]

    return orderedKeys.map((key) => ({
        key,
        label: formatResultLabel(key),
        count: resultCounts[key],
        rate: resultRates[key],
        previousRate: previousResultRates?.[key],
    }))
}

function getBooleanPassRate(
    metrics: EvaluationReportStoredMetrics,
    resultMetrics: EvaluationReportResultMetric[]
): number | undefined {
    if (metrics.pass_rate != null) {
        return metrics.pass_rate
    }
    const passCount = resultMetrics.find(({ key }) => key === 'pass')?.count
    const failCount = resultMetrics.find(({ key }) => key === 'fail')?.count
    if (passCount == null || failCount == null || passCount + failCount === 0) {
        return undefined
    }
    return (passCount / (passCount + failCount)) * 100
}

/** The pass rate a report stored, or one worked out from its pass and fail counts. */
export function reportPassRate(metrics: EvaluationReportStoredMetrics): number | undefined {
    return getBooleanPassRate(metrics, getResultMetrics(metrics))
}

export function summarizeEvaluationReportResults(metrics: EvaluationReportStoredMetrics): string {
    const resultMetrics = getResultMetrics(metrics)
    if (['boolean', 'numeric', 'categorical'].includes(metrics.output_type ?? 'boolean')) {
        const passRate = getBooleanPassRate(metrics, resultMetrics)
        const summaryParts = passRate == null ? [] : [`Pass rate ${formatResultRate(passRate, 1)}`]
        summaryParts.push(
            ...resultMetrics.filter(({ count }) => count != null).map(({ label, count }) => `${label} ${count}`)
        )
        return summaryParts.join(' · ') || '–'
    }

    const summary = resultMetrics
        .map(({ label, count, rate }) => {
            if (count == null && rate == null) {
                return null
            }
            if (count == null) {
                return `${label} ${formatResultRate(rate, 1)}`
            }
            return rate == null ? `${label} ${count}` : `${label} ${count} (${formatResultRate(rate, 1)})`
        })
        .filter((value): value is string => value != null)
        .join(' · ')
    return summary || '–'
}

function MetricsCard({ metrics }: { metrics: EvaluationReportStoredMetrics }): JSX.Element {
    const resultMetrics = getResultMetrics(metrics)
    const isBooleanMetrics = ['boolean', 'numeric', 'categorical'].includes(metrics.output_type ?? 'boolean')
    const passRate = isBooleanMetrics ? getBooleanPassRate(metrics, resultMetrics) : undefined
    const passRateDiff =
        passRate == null || metrics.previous_pass_rate == null ? null : passRate - metrics.previous_pass_rate
    const passRateDiffClass =
        passRateDiff == null || passRateDiff === 0 ? 'text-muted' : passRateDiff > 0 ? 'text-success' : 'text-danger'
    const passingRule =
        metrics.output_config && 'passing_rule' in metrics.output_config ? metrics.output_config.passing_rule : null

    return (
        <div className="rounded border bg-surface-primary p-3">
            {metrics.output_type === 'numeric' && passingRule && 'threshold' in passingRule && (
                <p className="text-sm text-muted">{`Passing rule used for this report: score ${passingRule.operator === 'gte' ? '≥' : '≤'} ${passingRule.threshold}`}</p>
            )}
            {metrics.output_type === 'categorical' && passingRule && 'categories' in passingRule && (
                <p className="text-sm text-muted">
                    Passing categories used for this report:{' '}
                    {passingRule.categories
                        .map(
                            (key) => metrics.output_config?.options?.find((option) => option.key === key)?.label ?? key
                        )
                        .join(', ') || 'None'}
                    . Every returned category must pass.
                </p>
            )}
            <div className="flex items-center gap-6 flex-wrap text-sm">
                <div>
                    <div className="text-muted text-xs">Total runs</div>
                    <div className="font-semibold">{metrics.total_runs ?? '–'}</div>
                </div>
                {passRate != null && (
                    <div>
                        <div className="text-muted text-xs">Pass rate</div>
                        <div className="font-semibold">
                            {formatResultRate(passRate)}
                            {passRateDiff != null && (
                                <span className={`text-xs ml-1 ${passRateDiffClass}`}>
                                    {passRateDiff === 0 ? '→' : passRateDiff > 0 ? '▲' : '▼'}{' '}
                                    {Math.abs(passRateDiff).toFixed(2)}pp vs previous
                                </span>
                            )}
                        </div>
                    </div>
                )}
                {resultMetrics.map(({ key, label, count, rate, previousRate }) => {
                    const diff = previousRate == null || rate == null ? null : rate - previousRate
                    const arrow = diff == null || diff === 0 ? '→' : diff > 0 ? '▲' : '▼'
                    const booleanCountClass =
                        isBooleanMetrics && key === 'pass'
                            ? 'text-success'
                            : isBooleanMetrics && key === 'fail'
                              ? 'text-danger'
                              : ''
                    if (count == null && (isBooleanMetrics || rate == null)) {
                        return null
                    }
                    return (
                        <div key={key}>
                            <div className="text-muted text-xs">{label}</div>
                            <div className={`font-semibold ${booleanCountClass}`}>
                                {count ?? '–'}
                                {!isBooleanMetrics && rate != null && (
                                    <span className="text-muted"> ({formatResultRate(rate)})</span>
                                )}
                                {!isBooleanMetrics && diff != null && (
                                    <span className="text-xs text-muted ml-1">
                                        {arrow} {Math.abs(diff).toFixed(2)}pp vs previous
                                    </span>
                                )}
                            </div>
                        </div>
                    )
                })}
                {metrics.previous_total_runs != null && (
                    <div>
                        <div className="text-muted text-xs">Previous runs</div>
                        <div className="font-semibold text-muted">{metrics.previous_total_runs}</div>
                    </div>
                )}
            </div>
        </div>
    )
}

export function EvaluationReportViewer({
    evaluationId,
    reportRun,
    onOpenTrace,
    onShowResults,
}: {
    evaluationId: string
    reportRun: EvaluationReportRun
    onOpenTrace: (traceId: string, eventId: string | null) => void
    /** Opens the Runs tab on this report's period. */
    onShowResults: () => void
}): JSX.Element {
    const content = reportRun.content
    const sections = content.sections ?? []
    const metrics = content.metrics ?? reportRun.metadata
    const citations = content.citations ?? []
    const metricsUnavailable = content.generation_status === 'metrics_unavailable'
    const deliveryFailed = reportRun.delivery_status === 'failed' || reportRun.delivery_status === 'partial_failure'

    return (
        <article className="flex flex-col gap-4">
            <header className="flex flex-col gap-1">
                <h2 className="mb-0 text-lg font-semibold">{content.title || 'Evaluation report'}</h2>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-secondary">
                    <span>
                        <TZLabel time={reportRun.period_start} {...PERIOD_FORMAT} /> to{' '}
                        <TZLabel time={reportRun.period_end} {...PERIOD_FORMAT} />
                    </span>
                    <ReportDeliveryTag status={reportRun.delivery_status} />
                </div>
            </header>

            {deliveryFailed && reportRun.delivery_errors.length > 0 && (
                <LemonBanner type={reportRun.delivery_status === 'failed' ? 'error' : 'warning'}>
                    <p className="mb-1">
                        {reportRun.delivery_status === 'failed'
                            ? "This report couldn't be sent."
                            : "This report couldn't be sent to every destination."}
                    </p>
                    <ul className="mb-0 text-xs">
                        {reportRun.delivery_errors.map((error, index) => (
                            <li key={index}>{error}</li>
                        ))}
                    </ul>
                </LemonBanner>
            )}

            {metricsUnavailable ? (
                <div className="rounded border p-3 text-sm text-secondary">{METRICS_UNAVAILABLE_MESSAGE}</div>
            ) : (
                <>
                    {metrics && <MetricsCard metrics={metrics} />}
                    <EvaluationReportPeriodChart evaluationId={evaluationId} reportRun={reportRun} />
                </>
            )}

            {sections.map((section, index) => (
                <section key={index} className="flex flex-col gap-1">
                    <h3 className="mb-0 text-sm font-semibold">{section.title?.trim() || 'Section'}</h3>
                    <ReportSectionContent section={section} citations={citations} />
                </section>
            ))}

            <EvaluationReportCitations citations={citations} onOpenTrace={onOpenTrace} />

            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onShowResults}
                    data-attr="llma-evaluation-report-show-results"
                >
                    See the results from this period
                </LemonButton>
            </div>
        </article>
    )
}
