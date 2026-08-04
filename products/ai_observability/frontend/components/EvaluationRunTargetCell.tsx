import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { EvaluationRun } from '../evaluations/types'
import { sanitizeTraceUrlSearchParams } from '../utils'

// Generation-target runs link to the specific event in the trace; trace-target
// runs (no generation id) link to the whole trace. Both land on the Evaluations tab.
export function EvaluationRunTargetCell({ run }: { run: EvaluationRun }): JSX.Element {
    const { searchParams } = useValues(router)

    if (!run.trace_id) {
        return <span className="font-mono text-sm text-muted">—</span>
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
