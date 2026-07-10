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
    const traceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })

    if (run.generation_id) {
        return (
            <div className="font-mono text-sm">
                <Link
                    to={
                        combineUrl(urls.aiObservabilityTrace(run.trace_id), {
                            ...traceSearchParams,
                            event: run.generation_id,
                            tab: 'evals',
                        }).url
                    }
                    className="text-primary"
                >
                    {run.generation_id.slice(0, 12)}...
                </Link>
            </div>
        )
    }
    if (run.trace_id) {
        return (
            <div className="font-mono text-sm">
                <Link
                    to={combineUrl(urls.aiObservabilityTrace(run.trace_id), { ...traceSearchParams, tab: 'evals' }).url}
                    className="text-primary"
                >
                    trace {run.trace_id.slice(0, 12)}...
                </Link>
            </div>
        )
    }
    return <span className="font-mono text-sm text-muted">—</span>
}
