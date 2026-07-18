import { useMemo, useState } from 'react'

import { LemonBadge, LemonButton, LemonCollapse, LemonDivider } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type {
    EvaluationReportCitation,
    EvaluationOutputType,
    EvaluationReportRun,
    EvaluationReportSection,
    EvaluationReportStoredMetrics,
} from '../types'

// Rewrite each cited generation or trace ID in the content into a markdown link
// to the trace viewer. Uses the structured citations list (not regex scanning) so:
// - only ids the agent explicitly cited get linked (no false positives)
// - the trace_id for the correct URL is guaranteed available
// - there's no ReDoS surface on arbitrary prose input
//
// Two-phase placeholder swap prevents double-wrapping when an id is mentioned
// multiple times, and prevents one id's generated link from being re-matched
// by a later citation. Wrapper variants (`uuid`, <uuid>, bare) are collapsed
// in descending specificity so the wrappers themselves get absorbed into the
// replacement rather than surviving around a link.
const SAFE_CITATION_LABEL_RE = /^[A-Za-z0-9._~-]{1,8}$/

function citationLinkLabel(citedId: string, isGenerationCitation: boolean): string {
    const preview = citedId.slice(0, 8)
    return SAFE_CITATION_LABEL_RE.test(preview) ? `${preview}...` : isGenerationCitation ? 'generation' : 'trace'
}

function linkifyCitations(content: string, citations: EvaluationReportCitation[]): string {
    if (citations.length === 0) {
        return content
    }
    const tokens: Array<{ token: string; link: string }> = []
    let out = content
    citations.forEach((c, idx) => {
        const citedId = c.generation_id || c.trace_id
        const traceId = c.trace_id || c.generation_id
        if (!citedId || !traceId) {
            return
        }
        const token = `\0CITE${idx}\0`
        const url = urls.aiObservabilityTrace(
            traceId,
            c.generation_id && c.trace_id ? { event: c.generation_id } : undefined
        )
        const link = `[\`${citationLinkLabel(citedId, Boolean(c.generation_id))}\`](${url})`
        const before = out
        out = out.split(`\`${citedId}\``).join(token)
        out = out.split(`<${citedId}>`).join(token)
        if (c.generation_id) {
            out = out.split(citedId).join(token)
        }
        if (out !== before) {
            tokens.push({ token, link })
        }
    })
    for (const { token, link } of tokens) {
        out = out.split(token).join(link)
    }
    return out
}

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

function ReportSectionContent({
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
    return (
        <LemonMarkdown lowKeyHeadings className="text-sm">
            {markdown}
        </LemonMarkdown>
    )
}

const RESULT_ORDER: Record<EvaluationOutputType, string[]> = {
    boolean: ['pass', 'fail', 'na'],
    sentiment: ['positive', 'neutral', 'negative'],
}

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

export function summarizeEvaluationReportResults(metrics: EvaluationReportStoredMetrics): string {
    if (metrics.metrics_available === false) {
        return 'Metrics unavailable'
    }
    const resultMetrics = getResultMetrics(metrics)
    if ((metrics.output_type ?? 'boolean') === 'boolean') {
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
    // A failed metrics query must not render as a real "0 runs" period.
    if (metrics.metrics_available === false) {
        return (
            <div className="bg-bg-light border rounded p-3 mb-3 text-sm text-muted">
                Metrics could not be computed for this period because the analytics store was temporarily unavailable.
                This does not mean no evaluations ran.
            </div>
        )
    }

    const resultMetrics = getResultMetrics(metrics)
    const isBooleanMetrics = (metrics.output_type ?? 'boolean') === 'boolean'
    const passRate = isBooleanMetrics ? getBooleanPassRate(metrics, resultMetrics) : undefined
    const passRateDiff =
        passRate == null || metrics.previous_pass_rate == null ? null : passRate - metrics.previous_pass_rate
    const passRateDiffClass =
        passRateDiff == null || passRateDiff === 0 ? 'text-muted' : passRateDiff > 0 ? 'text-success' : 'text-danger'

    return (
        <div className="bg-bg-light border rounded p-3 mb-3">
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

function DeliveryStatusBadge({ status }: { status: string }): JSX.Element {
    const statusMap: Record<string, { label: string; status: 'success' | 'warning' | 'danger' | 'muted' }> = {
        delivered: { label: 'Delivered', status: 'success' },
        generated: { label: 'Generated', status: 'success' },
        pending: { label: 'Pending', status: 'muted' },
        partial_failure: { label: 'Partial failure', status: 'warning' },
        failed: { label: 'Failed', status: 'danger' },
    }
    const info = statusMap[status] || { label: status, status: 'muted' as const }
    return <LemonBadge content={info.label} status={info.status} />
}

export function EvaluationReportViewer({
    reportRun,
    onClose,
    compact = false,
}: {
    reportRun: EvaluationReportRun
    onClose?: () => void
    /** When true, hides the header/close row — useful when the parent already provides framing (e.g. an expanded table row). */
    compact?: boolean
}): JSX.Element {
    const content = reportRun.content
    const sections = useMemo(() => content.sections ?? [], [content.sections])
    const metrics = content.metrics ?? reportRun.metadata
    const citations = useMemo(() => content.citations ?? [], [content.citations])

    // Default to executive summary (first section) expanded. Memoized so Expand/Collapse all
    // buttons can set the list deterministically.
    const sectionKeys = useMemo(() => sections.map((_, i) => i.toString()), [sections])
    const [expandedKeys, setExpandedKeys] = useState<string[]>(sections.length > 0 ? ['0'] : [])

    const allExpanded = expandedKeys.length === sectionKeys.length && sectionKeys.length > 0
    const allCollapsed = expandedKeys.length === 0

    return (
        <div>
            {!compact && (
                <>
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <h2 className="font-bold text-base mb-0">{content.title || 'Report'}</h2>
                            <DeliveryStatusBadge status={reportRun.delivery_status} />
                        </div>
                        {onClose && (
                            <LemonButton size="small" onClick={onClose}>
                                Close
                            </LemonButton>
                        )}
                    </div>
                    <div className="text-xs text-muted mb-3">
                        Period: {new Date(reportRun.period_start).toLocaleString()} –{' '}
                        {new Date(reportRun.period_end).toLocaleString()}
                    </div>

                    <LemonDivider className="my-3" />
                </>
            )}

            {compact && (
                <div className="flex items-center justify-between mb-2">
                    {content.title ? <h3 className="font-semibold text-sm mb-0">{content.title}</h3> : <div />}
                    {sections.length > 0 && (
                        <div className="flex gap-2">
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys(sectionKeys)}
                                disabledReason={allExpanded ? 'All sections already expanded' : undefined}
                            >
                                Expand all
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys([])}
                                disabledReason={allCollapsed ? 'All sections already collapsed' : undefined}
                            >
                                Collapse all
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}

            {metrics && <MetricsCard metrics={metrics} />}

            {sections.length > 0 && (
                <>
                    {!compact && (
                        <div className="flex justify-end gap-2 mb-2">
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys(sectionKeys)}
                                disabledReason={allExpanded ? 'All sections already expanded' : undefined}
                            >
                                Expand all
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys([])}
                                disabledReason={allCollapsed ? 'All sections already collapsed' : undefined}
                            >
                                Collapse all
                            </LemonButton>
                        </div>
                    )}

                    <LemonCollapse
                        multiple
                        size="small"
                        activeKeys={expandedKeys}
                        onChange={(keys) => setExpandedKeys(keys as string[])}
                        panels={sections.map((section, idx) => ({
                            key: idx.toString(),
                            header: section.title?.trim() || 'Section',
                            content: <ReportSectionContent section={section} citations={citations} />,
                        }))}
                    />
                </>
            )}

            {reportRun.delivery_errors.length > 0 && (
                <div className="mt-4 p-2 bg-danger-highlight rounded">
                    <h4 className="font-semibold text-sm text-danger">Delivery errors</h4>
                    <ul className="text-xs">
                        {reportRun.delivery_errors.map((err, i) => (
                            <li key={i}>{err}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}
