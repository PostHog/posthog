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
    const rows = citations.flatMap((citation) => {
        const target = citationTarget(citation)
        return target ? [{ citation, target }] : []
    })
    if (rows.length === 0) {
        return null
    }
    return (
        <section className="flex flex-col gap-2">
            <h3 className="mb-0 text-sm font-semibold">{`Cited examples (${rows.length})`}</h3>
            <ul className="flex flex-col gap-2">
                {rows.map(({ citation, target }, index) => {
                    return (
                        <li key={`${target.citedId}-${index}`} className="flex items-start justify-between gap-2">
                            <span className="min-w-0 text-sm">{citation.reason || `Cited ${target.label}`}</span>
                            {target.kind === 'session' ? (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    to={target.url}
                                    data-attr="llma-evaluation-report-citation-session"
                                >
                                    View session
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => onOpenTrace(target.traceId, target.eventId)}
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
