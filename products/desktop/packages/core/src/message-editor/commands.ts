import type { FeedbackType } from "@posthog/shared/analytics-events";

export function basename(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const idx = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  return idx >= 0 ? trimmed.slice(idx + 1) || trimmed : trimmed;
}

export interface ParsedCommandLine {
  name: string;
  args: string | undefined;
}

const COMMAND_LINE_REGEX = /^\/(\S+)(?:\s+(.*))?$/;

export function parseCommandLine(text: string): ParsedCommandLine | null {
  const match = text.match(COMMAND_LINE_REGEX);
  if (!match) return null;
  return { name: match[1], args: match[2] };
}

export interface FeedbackEventInput {
  taskId: string;
  taskRunId?: string;
  logUrl?: string;
  eventCount: number;
  feedbackType: FeedbackType;
  comment?: string;
}

export interface FeedbackEventPayload {
  task_id: string;
  task_run_id: string | undefined;
  log_url: string | undefined;
  event_count: number;
  feedback_type: FeedbackType;
  feedback_comment: string | undefined;
}

export function buildFeedbackEventPayload(
  input: FeedbackEventInput,
): FeedbackEventPayload {
  return {
    task_id: input.taskId,
    task_run_id: input.taskRunId,
    log_url: input.logUrl,
    event_count: input.eventCount,
    feedback_type: input.feedbackType,
    feedback_comment: input.comment?.trim() || undefined,
  };
}
