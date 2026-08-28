import type {
  AgentTurnFeedbackSentiment,
  AiFeedbackContextProperties,
  AiFeedbackProperties,
  AiMetricProperties,
  AiQualityRating,
  FeedbackType,
} from "@posthog/shared/analytics-events";

/** Sanity cap shared with the inbox note's FEEDBACK_NOTE_MAX_LENGTH. Capture only
 * rejects megabyte-scale events (and drops them whole, not truncated), so the cap
 * is a product bound, not a technical one. The editor enforces it before capture;
 * the slice here is the last-resort guard for other callers. */
export const AI_FEEDBACK_TEXT_MAX_LENGTH = 4000;

export interface AiFeedbackRunRef {
  taskId: string | null;
  taskRunId?: string;
}

function buildContext(
  run: AiFeedbackRunRef,
  extra: Partial<AiFeedbackContextProperties> = {},
): AiFeedbackContextProperties {
  return {
    $ai_session_id: run.taskId,
    $ai_trace_id: null,
    ai_product: "posthog_code",
    task_id: run.taskId,
    task_run_id: run.taskRunId,
    ...extra,
  };
}

export function sentimentToRating(
  sentiment: AgentTurnFeedbackSentiment,
): AiQualityRating {
  return sentiment === "positive" ? "good" : "bad";
}

export function buildTurnRatingMetric(input: {
  run: AiFeedbackRunRef;
  turnId: string;
  sentiment: AgentTurnFeedbackSentiment;
}): AiMetricProperties {
  return {
    ...buildContext(input.run, { turn_id: input.turnId }),
    $ai_metric_name: "quality",
    $ai_metric_value: sentimentToRating(input.sentiment),
  };
}

export interface SlashFeedbackInput {
  run: AiFeedbackRunRef;
  feedbackType: FeedbackType;
  comment?: string;
  eventCount: number;
}

export interface SlashFeedbackEvents {
  metric: AiMetricProperties | null;
  feedback: AiFeedbackProperties | null;
}

export function buildSlashFeedbackEvents(
  input: SlashFeedbackInput,
): SlashFeedbackEvents {
  const context = buildContext(input.run, {
    feedback_type: input.feedbackType,
    event_count: input.eventCount,
  });
  const comment = input.comment?.trim().slice(0, AI_FEEDBACK_TEXT_MAX_LENGTH);
  const metric: AiMetricProperties | null =
    input.feedbackType === "general"
      ? null
      : {
          ...context,
          $ai_metric_name: "quality",
          $ai_metric_value: input.feedbackType,
        };
  const feedback: AiFeedbackProperties | null = comment
    ? { ...context, $ai_feedback_text: comment }
    : null;
  return { metric, feedback };
}
