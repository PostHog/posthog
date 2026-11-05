import type { TraceFeedbackApi, TraceFeedbackSummaryApi, TraceNodeApi } from '../../../generated/api.schemas'
import { FeedbackChipData, FeedbackModeState, FeedbackPlacement, StepFeedback } from '../types'
import { nodeLabels } from './toTraceTree'

export function toFeedbackChip(summary: TraceFeedbackSummaryApi): FeedbackChipData | null {
    return summary.total > 0
        ? { total: summary.total, thumbsUp: summary.thumbsUp, thumbsDown: summary.thumbsDown }
        : null
}

/** Trace-level entries sit on the root, whose id is the trace id. */
export function toStepFeedback(feedback: TraceFeedbackApi): Record<string, StepFeedback> {
    // The root's key is the trace id, which is free-form, so a prototype key such as `constructor` must not resolve.
    const byStep: Record<string, StepFeedback> = Object.create(null)
    const entry = (nodeId: string): StepFeedback => (byStep[nodeId] ??= { scores: [], responseCount: 0 })
    for (const score of feedback.scores) {
        entry(score.nodeId).scores.push(score)
    }
    for (const response of feedback.responses) {
        entry(response.nodeId).responseCount += 1
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
    const placement = (nodeId: string): FeedbackPlacement => {
        const name = nodeId !== traceId ? labels.get(nodeId) : undefined
        return {
            step: name !== undefined ? { id: nodeId, name } : null,
            focused: nodeId === focusNodeId,
        }
    }
    return {
        status: 'ready',
        scores: feedback.scores.map((score) => ({ ...score, ...placement(score.nodeId) })),
        responses: feedback.responses.map((response) => ({ ...response, ...placement(response.nodeId) })),
        unanswered: feedback.unanswered,
        surveysFailed: feedback.surveyResponsesStatus === 'failed',
    }
}
