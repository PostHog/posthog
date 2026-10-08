import { urls } from 'scenes/urls'

import { EvaluationResultDisplayOptions, getEvaluationResultDisplay } from '../../../components/EvaluationResultTag'
import { EvaluationConfig, EvaluationRun } from '../../../evaluations/types'
import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalOutcome, EvalResult, EvalTarget } from '../types'

export interface EvalResultsContext {
    /** Every node of the trace, root first, to resolve and name what each run targets. */
    tree: TraceNodeApi[]
    viewedNodeId: string
    evaluations: EvaluationConfig[]
    detectorEvaluationIds: string[]
}

function displayOptions(run: EvaluationRun, context: EvalResultsContext): EvaluationResultDisplayOptions {
    const outputConfig = context.evaluations.find((evaluation) => evaluation.id === run.evaluation_id)?.output_config
    return {
        trueIsFailure: context.detectorEvaluationIds.includes(run.evaluation_id),
        passingRule: outputConfig?.passing_rule,
        categoryOptions: outputConfig?.options,
    }
}

function outcomeOf(run: EvaluationRun, tagType: string | undefined): EvalOutcome {
    if (run.status === 'failed') {
        return 'error'
    }
    if (run.status === 'running') {
        return 'pending'
    }
    if (tagType === 'success') {
        return 'pass'
    }
    if (tagType === 'danger') {
        return 'fail'
    }
    return tagType === 'none' ? 'unrated' : 'inconclusive'
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

function targetOf(run: EvaluationRun, labels: Map<string, string>, context: EvalResultsContext): EvalTarget | null {
    const nodeId = run.generation_id ?? context.tree[0]?.id
    if (!nodeId || nodeId === context.viewedNodeId) {
        return null
    }
    return { nodeId, label: labels.get(nodeId) ?? `${nodeId.slice(0, 12)}...` }
}

function producedAt(run: EvaluationRun): number {
    return new Date(run.start_time ?? run.timestamp).getTime()
}

export function toEvalResults(runs: EvaluationRun[], context: EvalResultsContext): EvalResult[] {
    const labels = nodeLabels(context.tree)
    return [...runs]
        .sort((a, b) => producedAt(b) - producedAt(a))
        .map((run) => {
            const display = getEvaluationResultDisplay(run, displayOptions(run, context))
            return {
                id: run.id,
                name: run.evaluation_name,
                href: urls.aiObservabilityEvaluation(run.evaluation_id),
                outcome: outcomeOf(run, display.type),
                label: display.label,
                reasoning: run.reasoning || null,
                timestamp: run.timestamp,
                isBackfill: !!run.backfill_id,
                target: targetOf(run, labels, context),
            }
        })
}
