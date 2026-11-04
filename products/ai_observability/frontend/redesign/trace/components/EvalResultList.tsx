import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { EvalsState } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { EvalResultRow } from './EvalResultRow'

export interface EvalResultListProps {
    evals: EvalsState
    onSelectNode: (nodeId: string) => void
}

export function EvalResultList({ evals, onSelectNode }: EvalResultListProps): JSX.Element {
    if (evals.status === 'loading') {
        return <LemonSkeleton repeat={3} className="h-8" />
    }
    if (evals.status === 'error') {
        return <ErrorCallout message={evals.errorMessage} />
    }
    if (evals.results.length === 0) {
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
            {evals.results.map((result) => (
                <EvalResultRow key={result.id} result={result} onSelectNode={onSelectNode} />
            ))}
        </ul>
    )
}
