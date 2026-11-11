import { LemonButton } from '@posthog/lemon-ui'

import type { EvaluationReportCitation } from '../types'
import { citationTarget } from './reportCitationLinks'

/** The examples the agent read, with its reason for each. Traces open in the drawer, sessions on their own page. */
export function EvaluationReportCitations({
    citations,
    onOpenTrace,
}: {
    citations: EvaluationReportCitation[]
    onOpenTrace: (traceId: string, eventId: string | null) => void
}): JSX.Element | null {
    const rows = citations
        .map((citation) => ({ citation, target: citationTarget(citation) }))
        .filter(({ target }) => target !== null)
    if (rows.length === 0) {
        return null
    }
    return (
        <section className="flex flex-col gap-2">
            <h3 className="mb-0 text-sm font-semibold">{`Cited examples (${rows.length})`}</h3>
            <ul className="flex flex-col gap-2">
                {rows.map(({ citation, target }, index) => {
                    const traceId = citation.trace_id || citation.generation_id
                    return (
                        <li key={`${target?.citedId}-${index}`} className="flex items-start justify-between gap-2">
                            <span className="min-w-0 text-sm">{citation.reason || `Cited ${target?.label}`}</span>
                            {citation.session_id || !traceId ? (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    to={target?.url}
                                    data-attr="llma-evaluation-report-citation-session"
                                >
                                    View session
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() =>
                                        onOpenTrace(
                                            traceId,
                                            citation.generation_id && citation.trace_id ? citation.generation_id : null
                                        )
                                    }
                                    data-attr="llma-evaluation-report-citation-trace"
                                >
                                    View trace
                                </LemonButton>
                            )}
                        </li>
                    )
                })}
            </ul>
        </section>
    )
}
