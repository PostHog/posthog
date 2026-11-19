import { LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { TraceEvaluationResultApi } from '../../../generated/api.schemas'
import { EvalOutcomeTag } from './EvalOutcomeTag'
import { ShortTimestamp } from './ShortTimestamp'

export interface EvalResultRowProps {
    result: TraceEvaluationResultApi
    viewedNodeId: string
    stepLabels: ReadonlyMap<string, string>
    onSelectNode: (nodeId: string) => void
}

export function EvalResultRow({ result, viewedNodeId, stepLabels, onSelectNode }: EvalResultRowProps): JSX.Element {
    const { targetNodeId } = result
    const targetLabel =
        targetNodeId === viewedNodeId ? null : (stepLabels.get(targetNodeId) ?? `${targetNodeId.slice(0, 12)}...`)
    return (
        <li className="flex flex-col gap-1 px-3 py-2">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                {result.evaluationId ? (
                    <Link
                        to={urls.aiObservabilityEvaluation(result.evaluationId)}
                        className="font-semibold text-sm"
                        data-attr="trace-view-eval-link"
                        targetBlankIcon={false}
                    >
                        {result.evaluationName}
                    </Link>
                ) : (
                    <span className="font-semibold text-sm">{result.evaluationName}</span>
                )}
                <EvalOutcomeTag outcome={result.outcome} label={result.label} />
                {result.isBackfill ? (
                    <LemonTag type="muted" size="small" title="A backfill over past data produced this result.">
                        Backfill
                    </LemonTag>
                ) : null}
                <span className="ml-auto flex items-center gap-2 text-xs text-secondary">
                    {targetLabel !== null ? (
                        <Link
                            onClick={() => onSelectNode(targetNodeId)}
                            className="max-w-60 truncate font-mono"
                            title={`Show ${targetLabel}`}
                            data-attr="trace-view-eval-target"
                        >
                            {targetLabel}
                        </Link>
                    ) : null}
                    <ShortTimestamp time={result.timestamp} />
                </span>
            </div>
            {result.reasoning ? <p className="m-0 text-secondary text-xs">{result.reasoning}</p> : null}
        </li>
    )
}
