/**
 * Merging the task activity timeline's three sources into one ordered list of rows.
 *
 * Kept out of the renderer so the ordering, collapsing and dedupe rules can be tested
 * without mounting anything — the same split `threadTimeline.ts` uses.
 *
 * The sources:
 *  - the task itself (created, and a terminal status for tasks with no event rows),
 *  - its thread messages: human messages plus the server-emitted event rows,
 *  - its comment threads, already collapsed one row per thread by the backend.
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
}

/** A prompt the task's author sent the agent, from the live session's own event stream.
 *  Only the fields the row needs, so core stays independent of the UI's item type. */
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
  | { kind: "run_status"; key: string; ts: number; status: string };

/** Rows in the same second still need a stable order, so each kind carries a rank.
 *  Ordering by rank rather than nudging timestamps (the old `updatedTs + 1`) keeps two
 *  events that genuinely share a timestamp from fighting over the same slot. */
const KIND_RANK: Record<ActivityRow["kind"], number> = {
  task_created: 0,
  event: 1,
  human_message: 1,
  user_message: 1,
  comment: 1,
  comment_state: 2,
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
  commentsEnabled = true,
}: {
  task: ActivityTaskLike;
  messages: TMessage[];
  commentThreads: TComment[];
  userMessages?: UserMessageLike[];
  /** False drops the comment feed entirely, rather than leaving the renderer to hide
   *  rows it was handed. */
  commentsEnabled?: boolean;
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

  for (const message of messages) {
    const event = parseActivityEvent(message);
    if (!event) {
      if ((message.author_kind ?? "human") === "human") {
        rows.push({
          kind: "human_message",
          key: `message-${message.id}`,
          ts: timestamp(message.created_at),
          message,
        });
      }
      continue;
    }
    const identity = `${event.kind}:${eventIdentity(event)}`;
    if (seenEvents.has(identity)) continue;
    seenEvents.add(identity);
    if (event.kind === "run_failed") hasTerminalEvent = true;
    rows.push({
      kind: "event",
      key: `event-${message.id}`,
      ts: timestamp(message.created_at),
      event,
      message,
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

  if (commentsEnabled) {
    for (const thread of commentThreads) {
      rows.push({
        kind: "comment",
        key: `comment-${thread.id}`,
        ts: timestamp(thread.lastActivityAt),
        thread,
      });
      // Resolve and reopen are state changes with an author and a time, so they get their
      // own row rather than folding into the thread they close.
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

/** What makes an event unique in the world, for the dedupe guard above. */
function eventIdentity(event: ActivityEvent): string {
  switch (event.kind) {
    case "run_started":
    case "run_failed":
    case "awaiting_input":
      return event.payload.runId;
    case "artifact_created":
    case "artifact_revised":
      return `${event.payload.artifactId}:${event.payload.version}`;
    case "canvas_created":
      return event.payload.name;
    case "pr_created":
    case "pr_merged":
    case "pr_closed":
      return event.payload.prUrl;
    case "message_forwarded":
      return event.payload.messageId;
  }
}
