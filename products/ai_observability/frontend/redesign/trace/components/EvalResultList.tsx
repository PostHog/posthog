import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { TraceEvaluationResultApi, TraceNodeApi } from '../../../generated/api.schemas'
import { ErrorCallout } from './ErrorCallout'
import { EvalResultRow } from './EvalResultRow'

export interface EvalResultListProps {
    /** Null until the results have loaded. */
    results: TraceEvaluationResultApi[] | null
    failed: boolean
    viewedNode: TraceNodeApi
    stepLabels: ReadonlyMap<string, string>
    onSelectNode: (nodeId: string) => void
}

export function EvalResultList({
    results,
    failed,
    viewedNode,
    stepLabels,
    onSelectNode,
}: EvalResultListProps): JSX.Element {
    if (failed) {
        return <ErrorCallout message="Evaluation results could not be loaded. Reload the page to try again." />
    }
    if (!results) {
        return <LemonSkeleton repeat={3} className="h-8" />
    }
    const shown =
        viewedNode.kind === 'trace' ? results : results.filter((result) => result.targetNodeId === viewedNode.id)
    if (shown.length === 0) {
        return (
            <p className="m-0 text-secondary">
                <span>No evaluations ran on this step. </span>
                <Link to={urls.aiObservabilityEvaluations()} data-attr="trace-view-evals-setup-link">
                    Set up evaluations
                </Link>
            </p>
        )
    }
    return (
        <ul className="m-0 list-none divide-y divide-primary rounded border border-primary bg-surface-primary p-0">
            {shown.map((result) => (
                <EvalResultRow
                    key={result.id}
                    result={result}
                    viewedNodeId={viewedNode.id}
                    stepLabels={stepLabels}
                    onSelectNode={onSelectNode}
                />
            ))}
        </ul>
    )
}
