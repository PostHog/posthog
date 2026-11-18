import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { EvaluationReportCitation, EvaluationReportRun, EvaluationReportSection } from '../types'
import { EvaluationReportCitations } from './EvaluationReportCitations'
import { EvaluationReportMetrics } from './EvaluationReportMetrics'
import { linkifyCitations } from './reportCitationLinks'
import { ReportDeliveryTag } from './ReportDeliveryTag'
import { reportHeadline } from './reportHeadline'

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

const PERIOD_FORMAT = { formatDate: 'MMM D', formatTime: 'HH:mm' }

const METRICS_UNAVAILABLE_MESSAGE =
    'Metrics could not be calculated for this period because evaluation data was temporarily unavailable. This does not mean that no evaluations ran.'

export function EvaluationReportViewer({
    reportRun,
    onOpenTrace,
    onShowResults,
}: {
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
                    <ReportDeliveryTag run={reportRun} />
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
                metrics && <EvaluationReportMetrics metrics={metrics} headline={reportHeadline(reportRun)} />
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
