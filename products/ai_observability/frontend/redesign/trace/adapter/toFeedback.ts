import type { TraceFeedbackApi, TraceFeedbackSummaryApi, TraceNodeApi } from '../../../generated/api.schemas'
import { FeedbackChipData, FeedbackModeState, FeedbackPlacement, StepFeedback } from '../types'
import { nodeLabels } from './toEvalResults'

export function toFeedbackChip(summary: TraceFeedbackSummaryApi): FeedbackChipData | null {
    return summary.total > 0
        ? { total: summary.total, thumbsUp: summary.thumbsUp, thumbsDown: summary.thumbsDown }
        : null
}

function nodeIdOf(response: TraceFeedbackApi['responses'][number]): string | null {
    return response.kind === 'text' ? response.nodeId : null
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
    // The root's key is the trace id, which is free-form, so a prototype key such as `constructor` must not resolve.
    const byStep: Record<string, StepFeedback> = Object.create(null)
    const entry = (nodeId: string | null): StepFeedback =>
        (byStep[treeStepId(nodeId, labels) ?? traceId] ??= { scores: [], responseCount: 0 })
    for (const score of feedback.scores) {
        entry(score.nodeId).scores.push(score)
    }
    for (const response of feedback.responses) {
        entry(nodeIdOf(response)).responseCount += 1
    }
    return byStep
}

export function stepFeedbackOf(stepFeedback: Record<string, StepFeedback>, nodeId: string): StepFeedback | null {
    return Object.hasOwn(stepFeedback, nodeId) ? stepFeedback[nodeId] : null
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
        responses: feedback.responses.map((response) => ({ ...response, ...placement(nodeIdOf(response)) })),
        unanswered: feedback.unanswered,
        surveysFailed: feedback.surveyResponsesStatus === 'failed',
    }
}
