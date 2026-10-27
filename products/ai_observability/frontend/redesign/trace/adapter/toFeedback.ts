import type { TraceFeedbackApi, TraceFeedbackSummaryApi, TraceNodeApi } from '../../../generated/api.schemas'
import { FeedbackChipData, FeedbackModeState, FeedbackPlacement, StepFeedback } from '../types'
import { nodeLabels } from './toEvalResults'

export function toFeedbackChip(summary: TraceFeedbackSummaryApi): FeedbackChipData | null {
    return summary.total > 0 ? { total: summary.total } : null
}

/** The step an entry belongs to in this tree. Entries on the whole trace, or on a step the tree lacks, are null. */
function treeStepId(nodeId: string | null, labels: Map<string, string>): string | null {
    return nodeId !== null && labels.has(nodeId) ? nodeId : null
}

/** Trace-level entries sit on the root, whose id is the trace id. */
export function toStepFeedback(
    feedback: TraceFeedbackApi,
    tree: TraceNodeApi[],
    traceId: string
): Record<string, StepFeedback> {
    const labels = nodeLabels(tree)
    const byStep: Record<string, StepFeedback> = {}
    const entry = (nodeId: string | null): StepFeedback =>
        (byStep[treeStepId(nodeId, labels) ?? traceId] ??= { scores: [], textCount: 0 })
    for (const score of feedback.scores) {
        entry(score.nodeId).scores.push(score)
    }
    for (const response of feedback.responses) {
        entry(response.nodeId).textCount += 1
    }
    return byStep
}

export interface FeedbackModeArgs {
    feedback: TraceFeedbackApi
    tree: TraceNodeApi[]
    traceId: string
    /** The step the mode was opened from, the trace id for the root. */
    focusNodeId: string | null
}

export function toFeedbackMode({
    feedback,
    tree,
    traceId,
    focusNodeId,
}: FeedbackModeArgs): Extract<FeedbackModeState, { status: 'ready' }> {
    const labels = nodeLabels(tree)
    const placement = (nodeId: string | null): FeedbackPlacement => {
        const stepId = treeStepId(nodeId, labels)
        return {
            step: stepId !== null ? { id: stepId, name: labels.get(stepId) ?? stepId } : null,
            focused: focusNodeId !== null && (stepId ?? traceId) === focusNodeId,
        }
    }
    return {
        status: 'ready',
        scores: feedback.scores.map((score) => ({ ...score, ...placement(score.nodeId) })),
        responses: feedback.responses.map((response) => ({ ...response, ...placement(response.nodeId) })),
    }
}
