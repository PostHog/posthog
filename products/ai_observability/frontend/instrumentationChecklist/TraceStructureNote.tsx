import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { AIObservabilityInstrumentationCheckEnumApi } from '../generated/api.schemas'
import { instrumentationChecklistLogic } from './instrumentationChecklistLogic'

// Mirrors the trace_structure check's own signals, `spans > 0 or events_with_parent > 0`.
function hasTraceStructure(events: LLMTraceEvent[]): boolean {
    return events.some((event) => event.event === '$ai_span' || !!event.properties.$ai_parent_id)
}

/**
 * Says why a trace tree holds nothing but LLM calls, next to the tree itself.
 *
 * Gated on `warningForCheck` alone, unlike the list surfaces, which route through
 * `useInstrumentationWarning` to suppress the verdict once the user narrows the view. One trace has
 * no filters that could explain away a missing span, and that guard reads the same keyed
 * `aiObservabilitySharedLogic` the list tabs write to, whose date range and property filters persist
 * in localStorage, so it would silence the note here based on a view the reader is not looking at.
 *
 * The trace on screen gates it instead. The project verdict is graded over a 30 day window, while a
 * single trace renders from the events table past that window, so a project that stopped emitting
 * spans months ago can still open a trace that visibly has them.
 */
export function TraceStructureNote({ events }: { events: LLMTraceEvent[] }): JSX.Element | null {
    const { warningForCheck } = useValues(instrumentationChecklistLogic)
    const warning = warningForCheck(AIObservabilityInstrumentationCheckEnumApi.TraceStructure)

    if (!warning || hasTraceStructure(events)) {
        return null
    }

    return (
        <LemonBanner type="info" square className="shrink-0 border-x-0 border-b-0">
            <p className="text-xs font-normal">
                <span className="font-medium">No spans in this trace.</span> {warning.detail}{' '}
                <Link
                    to={warning.docs_url}
                    target="_blank"
                    targetBlankIcon
                    data-attr="llma-trace-structure-instrumentation-docs"
                >
                    Learn more
                </Link>
            </p>
        </LemonBanner>
    )
}
