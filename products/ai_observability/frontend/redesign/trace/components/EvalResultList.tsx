import { LemonSkeleton } from '@posthog/lemon-ui'

import { EvalsState } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { EvalResultRow } from './EvalResultRow'

export interface EvalResultListProps {
    evals: EvalsState
}

export function EvalResultList({ evals }: EvalResultListProps): JSX.Element {
    if (evals.status === 'loading') {
        return <LemonSkeleton repeat={3} className="h-8" />
    }
    if (evals.status === 'error') {
        return <ErrorCallout message={evals.errorMessage} />
    }
    if (evals.results.length === 0) {
        return <p className="m-0 text-secondary">No evaluations ran on this step.</p>
    }
    return (
        <ul className="m-0 list-none divide-y divide-primary rounded border border-primary bg-surface-primary p-0">
            {evals.results.map((result) => (
                <EvalResultRow key={result.id} result={result} />
            ))}
        </ul>
    )
}
