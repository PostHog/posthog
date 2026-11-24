import { useValues } from 'kea'
import { router } from 'kea-router'

import { dayjs } from 'lib/dayjs'

import { reportCitationSamplesLogic } from '../reportCitationSamplesLogic'
import type { EvaluationReportCitation } from '../types'
import { EvaluationDrawerSection } from './EvaluationDrawerSection'
import { type CitationTarget, citationTarget } from './reportCitationLinks'
import { TraceSampleRow } from './TraceSampleRow'
import { TraceSampleRowSkeleton } from './TraceSampleRowSkeleton'

type CitationRow = { citation: EvaluationReportCitation; target: CitationTarget }

function CitationRows({
    runId,
    periodStart,
    periodEnd,
    rows,
    onOpenTrace,
}: {
    runId: string
    periodStart: string
    periodEnd: string
    rows: CitationRow[]
    onOpenTrace: (traceId: string, eventId: string | null) => void
}): JSX.Element {
    const { samples } = useValues(
        reportCitationSamplesLogic({
            runId,
            traceIds: rows.flatMap(({ target }) => (target.kind === 'trace' ? [target.traceId] : [])),
            // A cited trace can start before the period that its result falls in.
            earliest: dayjs(periodStart).subtract(1, 'day').toISOString(),
            latest: periodEnd,
        })
    )
    return (
        <div className="overflow-hidden rounded border border-primary divide-y divide-primary">
            {rows.map(({ citation, target }, index) =>
                target.kind === 'trace' && !samples ? (
                    <TraceSampleRowSkeleton key={`${target.citedId}-${index}`} />
                ) : (
                    <TraceSampleRow
                        key={`${target.citedId}-${index}`}
                        sample={
                            target.kind === 'trace'
                                ? (samples?.[target.traceId] ?? { preview: null, person: null })
                                : null
                        }
                        timestamp={null}
                        note={citation.reason || `Cited ${target.label}`}
                        onOpen={() =>
                            target.kind === 'session'
                                ? router.actions.push(target.url)
                                : onOpenTrace(target.traceId, target.eventId)
                        }
                        data-attr={
                            target.kind === 'session'
                                ? 'llma-evaluation-report-citation-session'
                                : 'llma-evaluation-report-citation-trace'
                        }
                    />
                )
            )}
        </div>
    )
}

/** The examples the agent read, with its reason for each. Traces open in the drawer, sessions on their own page. */
export function EvaluationReportCitations({
    runId,
    periodStart,
    periodEnd,
    citations,
    onOpenTrace,
}: {
    runId: string
    periodStart: string
    periodEnd: string
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
        <EvaluationDrawerSection
            title="Cited examples"
            subtitle="The traces the report points to. Open one to read it."
        >
            <CitationRows
                runId={runId}
                periodStart={periodStart}
                periodEnd={periodEnd}
                rows={rows}
                onOpenTrace={onOpenTrace}
            />
        </EvaluationDrawerSection>
    )
}
