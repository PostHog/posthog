import { urls } from 'scenes/urls'

import type { TraceEvaluationResultApi, TraceNodeApi } from '../../../generated/api.schemas'
import { EvalResult, EvalTarget } from '../types'

export interface EvalResultsContext {
    /** Every node of the trace, root first, to name what each result targets. */
    tree: TraceNodeApi[]
    viewedNodeId: string
}

function flatten(nodes: TraceNodeApi[]): TraceNodeApi[] {
    return nodes.flatMap((node) => [node, ...flatten(node.children)])
}

// Two steps can share a name, such as two calls to the same model, so repeated names get their position.
function nodeLabels(tree: TraceNodeApi[]): Map<string, string> {
    const nodes = flatten(tree)
    const totals = new Map<string, number>()
    nodes.forEach((node) => totals.set(node.name, (totals.get(node.name) ?? 0) + 1))
    const seen = new Map<string, number>()
    return new Map(
        nodes.map((node) => {
            const position = (seen.get(node.name) ?? 0) + 1
            seen.set(node.name, position)
            return [node.id, (totals.get(node.name) ?? 0) > 1 ? `${node.name} #${position}` : node.name]
        })
    )
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
