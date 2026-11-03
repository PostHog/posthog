import { urls } from 'scenes/urls'

import type { TraceEvaluationResultApi, TraceNodeApi } from '../../../generated/api.schemas'
import { EvalResult, EvalTarget } from '../types'
import { nodeLabels } from './toTraceTree'

export interface EvalResultsContext {
    /** Every node of the trace, root first, to name what each result targets. */
    tree: TraceNodeApi[]
    viewedNodeId: string
}

function targetOf(
    result: TraceEvaluationResultApi,
    labels: Map<string, string>,
    viewedNodeId: string
): EvalTarget | null {
    const nodeId = result.targetNodeId
    if (nodeId === viewedNodeId) {
        return null
    }
    return { nodeId, label: labels.get(nodeId) ?? `${nodeId.slice(0, 12)}...` }
}

export function toEvalResults(results: TraceEvaluationResultApi[], context: EvalResultsContext): EvalResult[] {
    const labels = nodeLabels(context.tree)
    return results.map((result) => ({
        id: result.id,
        name: result.evaluationName,
        href: result.evaluationId ? urls.aiObservabilityEvaluation(result.evaluationId) : null,
        outcome: result.outcome,
        label: result.label,
        reasoning: result.reasoning,
        timestamp: result.timestamp,
        isBackfill: result.isBackfill,
        target: targetOf(result, labels, context.viewedNodeId),
    }))
}
