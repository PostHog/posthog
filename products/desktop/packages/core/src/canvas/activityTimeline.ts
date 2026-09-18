/**
 * Merges the task, its thread messages and its comment threads into one ordered list of rows.
 *
 * Kept out of the renderer so the ordering, collapsing and dedupe rules can be tested without
 * mounting anything, the same split `threadTimeline.ts` uses.
 */

import {
  type ActivityEvent,
  parseActivityEvent,
} from "@posthog/core/canvas/activityEvents";
import type { ThreadMessageLike } from "@posthog/core/canvas/threadTimeline";

export interface CommentThreadLike {
  id: string;
  lastActivityAt: string;
  mentionedUserIds: number[];
  resolved: boolean;
  stateEvent: { state: string; createdAt: string } | null;
}

export interface ActivityTaskLike {
  id: string;
  createdAt: string;
  updatedAt: string;
  latestRunId?: string | null;
  latestRunStatus?: string | null;
  /** Tasks from before the thread announcements record their pull request only here. */
  latestRunPrUrl?: string | null;
}

/** Only the fields the row needs, so core stays independent of the UI's item type. */
export interface UserMessageLike {
  id: string;
  content: string;
  timestamp: number;
}

export type ActivityRow<
  TMessage extends ThreadMessageLike = ThreadMessageLike,
  TComment extends CommentThreadLike = CommentThreadLike,
> =
  | { kind: "task_created"; key: string; ts: number }
  | {
      kind: "event";
      key: string;
      ts: number;
      event: ActivityEvent;
      message: TMessage;
      /** Which run of the task a `run_started` row is, counted over the feed. The backend
       *  cannot number these without racing two concurrent creations onto one number. */
      runOrdinal?: number;
    }
  | { kind: "human_message"; key: string; ts: number; message: TMessage }
  | { kind: "user_message"; key: string; ts: number; item: UserMessageLike }
  | { kind: "comment"; key: string; ts: number; thread: TComment }
  | {
      kind: "comment_state";
      key: string;
      ts: number;
      thread: TComment;
      state: string;
    }
  | { kind: "run_status"; key: string; ts: number; status: string }
  | { kind: "run_output_pr"; key: string; ts: number; prUrl: string };

/** Rows sharing a timestamp still need a stable order. Ranking them beats nudging the
 *  timestamps, which makes two events that genuinely share one fight over a slot. */
const KIND_RANK: Record<ActivityRow["kind"], number> = {
  task_created: 0,
  event: 1,
  human_message: 1,
  user_message: 1,
  comment: 1,
  comment_state: 2,
  run_output_pr: 2,
  run_status: 3,
};

function timestamp(value: string | undefined): number {
  const parsed = Date.parse(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
}

export function buildActivityTimeline<
  TMessage extends ThreadMessageLike,
  TComment extends CommentThreadLike,
>({
  task,
  messages,
  commentThreads,
  userMessages = [],
}: {
  task: ActivityTaskLike;
  messages: TMessage[];
  commentThreads: TComment[];
  userMessages?: UserMessageLike[];
}): ActivityRow<TMessage, TComment>[] {
  const rows: ActivityRow<TMessage, TComment>[] = [
    {
      kind: "task_created",
      key: "task-created",
      ts: timestamp(task.createdAt),
    },
  ];

  // Two paths can observe the same thing (the agent's own output and the GitHub webhook
  // backstop), and the backend keys writes to stop that. A client-side guard on the same
  // identity covers rows written before the key existed.
  const seenEvents = new Set<string>();
  let hasTerminalEvent = false;
  let hasPrEvent = false;
  let runStartedSeen = 0;

  for (const message of messages) {
    const event = parseActivityEvent(message);
    if (!event) {
      // A message carrying an event we couldn't parse is a future event kind, not a human
      // reply; drawing it as one would misattribute a server announcement to the person.
      if (!message.event && (message.author_kind ?? "human") === "human") {
        rows.push({
          kind: "human_message",
          key: `message-${message.id}`,
          ts: timestamp(message.created_at),
          message,
        });
      }
      continue;
    }
    const identity = `${event.kind}:${eventIdentity(event, message)}`;
    if (seenEvents.has(identity)) continue;
    seenEvents.add(identity);
    if (event.kind === "run_failed") hasTerminalEvent = true;
    if (event.kind === "run_started") runStartedSeen += 1;
    if (
      event.kind === "pr_created" ||
      event.kind === "pr_merged" ||
      event.kind === "pr_closed"
    ) {
      hasPrEvent = true;
    }
    rows.push({
      kind: "event",
      key: `event-${message.id}`,
      ts: timestamp(message.created_at),
      event,
      message,
      ...(event.kind === "run_started" ? { runOrdinal: runStartedSeen } : {}),
    });
  }

  for (const item of userMessages) {
    rows.push({
      kind: "user_message",
      key: `user-message-${item.id}`,
      ts: item.timestamp,
      item,
    });
  }

  for (const thread of commentThreads) {
    rows.push({
      kind: "comment",
      key: `comment-${thread.id}`,
      ts: timestamp(thread.lastActivityAt),
      thread,
    });
    if (thread.stateEvent) {
      rows.push({
        kind: "comment_state",
        key: `comment-state-${thread.id}`,
        ts: timestamp(thread.stateEvent.createdAt),
        thread,
        state: thread.stateEvent.state,
      });
    }
  }

  // A run that recorded its pull request only in its output still gets a row, so a task
  // whose PR was never announced in the thread doesn't hide it entirely.
  if (task.latestRunPrUrl && !hasPrEvent) {
    rows.push({
      kind: "run_output_pr",
      key: `run-output-pr-${task.latestRunId ?? "latest"}`,
      ts: timestamp(task.updatedAt) || timestamp(task.createdAt),
      prUrl: task.latestRunPrUrl,
    });
  }

  // Fallback for tasks whose runs predate the event rows: derive the ending from the task.
  const status = task.latestRunStatus ?? null;
  if (status && isTerminalRunStatus(status) && !hasTerminalEvent) {
    rows.push({
      kind: "run_status",
      key: `run-status-${task.latestRunId ?? "latest"}`,
      ts: timestamp(task.updatedAt) || timestamp(task.createdAt),
      status,
    });
  }

  return rows.sort(
    (left, right) =>
      left.ts - right.ts ||
      KIND_RANK[left.kind] - KIND_RANK[right.kind] ||
      left.key.localeCompare(right.key),
  );
}

function isTerminalRunStatus(status: string): boolean {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}

function eventIdentity(
  event: ActivityEvent,
  message: ThreadMessageLike,
): string {
  switch (event.kind) {
    case "run_started":
    case "run_failed":
      return event.payload.runId;
    // A run can ask for input more than once, and each ask is its own row. Only the kinds
    // two paths can both report need an identity that ignores which message carried them.
    case "awaiting_input":
      return `${event.payload.runId}:${message.created_at}`;
    case "commits_pushed":
      // The head SHA identifies the push, the way the backend keys it.
      return event.payload.commits.at(-1)?.sha ?? event.payload.runId;
    case "artifact_created":
    case "artifact_revised":
      return `${event.payload.artifactId}:${event.payload.version}`;
    case "canvas_created":
      return event.payload.name;
    // One row per comment id: the backend emits roots and state changes only.
    case "comment_added":
    case "comment_state_changed":
      return event.payload.commentId;
    case "pr_created":
    case "pr_merged":
    case "pr_closed":
      return event.payload.prUrl;
    case "message_forwarded":
      return event.payload.messageId;
    case "task_handed_off":
      // Each handoff is its own row; only a duplicate write of the same one collapses.
      return message.id;
  }
}
