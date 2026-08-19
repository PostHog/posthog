import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { AIObservabilityInstrumentationCheckEnumApi } from '../generated/api.schemas'
import { instrumentationChecklistLogic } from './instrumentationChecklistLogic'

/**
 * Says why a trace tree holds nothing but LLM calls, next to the tree itself.
 *
 * Gated on `warningForCheck` alone, unlike the list surfaces, which route through
 * `useInstrumentationWarning` to suppress the verdict once the user narrows the view. That guard
 * reads a keyed `aiObservabilitySharedLogic` carrying a different key here, and one trace has no
 * filters that could explain away a missing span, so applying it would only silence the note for
 * unrelated reasons.
 */
export function TraceStructureNote(): JSX.Element | null {
    const { warningForCheck } = useValues(instrumentationChecklistLogic)
    const warning = warningForCheck(AIObservabilityInstrumentationCheckEnumApi.TraceStructure)

    if (!warning) {
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
