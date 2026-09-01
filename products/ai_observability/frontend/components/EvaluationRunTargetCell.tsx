import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { EvaluationRun } from '../evaluations/types'
import { sanitizeTraceUrlSearchParams } from '../utils'

// Generation-target runs link to the specific event in the trace; trace-target
// runs (no generation id) link to the whole trace. Both land on the Evaluations tab.
// Session-target runs have no trace id at all and link to the session instead.
export function EvaluationRunTargetCell({ run }: { run: EvaluationRun }): JSX.Element {
    const { searchParams } = useValues(router)

    if (!run.trace_id) {
        if (!run.session_id) {
            return <span className="font-mono text-sm text-muted">—</span>
        }
        return (
            <div className="font-mono text-sm">
                <Link to={urls.aiObservabilitySession(run.session_id)} className="text-primary">
                    session {run.session_id.slice(0, 12)}...
                </Link>
            </div>
        )
    }

    // No timestamp param on purpose: the run's timestamp can be long after the trace
    // (debounce window, manual re-runs), and without one the trace query scans from the
    // beginning, which always finds the trace.
    const to = combineUrl(urls.aiObservabilityTrace(run.trace_id), {
        ...sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true }),
        tab: 'evals',
        ...(run.generation_id ? { event: run.generation_id } : {}),
    }).url
    const label = run.generation_id ? `${run.generation_id.slice(0, 12)}...` : `trace ${run.trace_id.slice(0, 12)}...`

    return (
        <div className="font-mono text-sm">
            <Link to={to} className="text-primary">
                {label}
            </Link>
        </div>
    )
}
