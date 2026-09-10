/**
 * The JSON view of one task's activity that a canvas reads through
 * `ph.taskActivity()`.
 *
 * The React timeline renders `ActivityRow` directly, but a canvas runs in a
 * sandboxed iframe: it can only receive structured-clone data, and it must not
 * depend on the row union, whose shape changes with the renderer. So the host
 * flattens each row to a printable line here, and this file is the contract a
 * canvas author writes against.
 */

import { prLabel } from "./activityEvents";
import type { ActivityRow } from "./activityTimeline";

export interface CanvasTaskActivityRow {
  /** Stable across polls, so a canvas can key its list on it. */
  key: string;
  /** The event name for a server event row, else the row kind. */
  kind: string;
  /** ISO 8601, UTC. */
  at: string;
  /** One line, ready to print. */
  title: string;
  /** The body of a message, the summary of a failure, or null. */
  detail: string | null;
  /** Where the row points, for the rows that point somewhere. */
  url: string | null;
}

export interface CanvasTaskActivitySnapshot {
  task: {
    id: string;
    title: string;
    /** The status of the latest run, or null when the task never ran. */
    status: string | null;
    createdAt: string;
    updatedAt: string;
  };
  /** Oldest first, the order the timeline reads in. */
  rows: CanvasTaskActivityRow[];
  /** True when older rows were dropped to hold the row limit. */
  truncated: boolean;
}

export const CANVAS_TASK_ACTIVITY_DEFAULT_LIMIT = 100;
export const CANVAS_TASK_ACTIVITY_MAX_LIMIT = 500;
/** A message can be very long, and the whole snapshot crosses the bridge on
 *  every poll, so each line carries a preview instead of the full body. */
const MAX_DETAIL_LENGTH = 500;

function detail(value: string | null | undefined): string | null {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return null;
  return trimmed.length > MAX_DETAIL_LENGTH
    ? `${trimmed.slice(0, MAX_DETAIL_LENGTH)}…`
    : trimmed;
}

function isoTime(ts: number): string {
  return Number.isFinite(ts) && ts > 0
    ? new Date(ts).toISOString()
    : new Date(0).toISOString();
}

function eventLine(row: Extract<ActivityRow, { kind: "event" }>): {
  kind: string;
  title: string;
  detail: string | null;
  url: string | null;
} {
  const { event } = row;
  switch (event.kind) {
    case "run_started":
      return {
        kind: event.kind,
        title: row.runOrdinal ? `Run ${row.runOrdinal} started` : "Run started",
        detail: detail(event.payload.branch || event.payload.environment),
        url: null,
      };
    case "run_failed":
      return {
        kind: event.kind,
        title: "Run failed",
        detail: detail(event.payload.errorSummary),
        url: null,
      };
    case "awaiting_input":
      return {
        kind: event.kind,
        title: "Waiting for input",
        detail: null,
        url: null,
      };
    case "commits_pushed": {
      const { total, branch, commits } = event.payload;
      const head = commits.at(-1);
      return {
        kind: event.kind,
        title:
          total === 1
            ? `Pushed 1 commit to ${branch}`
            : `Pushed ${total} commits to ${branch}`,
        detail: detail(head?.subject),
        url: head?.url ?? null,
      };
    }
    case "artifact_created":
      return {
        kind: event.kind,
        title: `Added ${event.payload.name}`,
        detail: null,
        url: null,
      };
    case "artifact_revised":
      return {
        kind: event.kind,
        title: `Updated ${event.payload.name}`,
        detail: `Version ${event.payload.version}`,
        url: null,
      };
    case "canvas_created":
      return {
        kind: event.kind,
        title: `Created canvas ${event.payload.name}`,
        detail: null,
        url: event.payload.url,
      };
    case "comment_added":
      return {
        kind: event.kind,
        title: "New comment",
        detail: detail(event.payload.targetName),
        url: null,
      };
    case "comment_state_changed":
      return {
        kind: event.kind,
        title:
          event.payload.state === "resolved"
            ? "Comment resolved"
            : "Comment reopened",
        detail: detail(event.payload.targetName),
        url: null,
      };
    case "pr_created":
      return {
        kind: event.kind,
        title: `Opened ${prLabel(event.payload)}`,
        detail: null,
        url: event.payload.prUrl,
      };
    case "pr_merged":
      return {
        kind: event.kind,
        title: `Merged ${prLabel(event.payload)}`,
        detail: null,
        url: event.payload.prUrl,
      };
    case "pr_closed":
      return {
        kind: event.kind,
        title: `Closed ${prLabel(event.payload)}`,
        detail: null,
        url: event.payload.prUrl,
      };
    case "message_forwarded":
      return {
        kind: event.kind,
        title: "Message sent to the agent",
        detail: null,
        url: null,
      };
    case "task_handed_off":
      return {
        kind: event.kind,
        title: `Handed off to ${event.payload.toDisplayName}`,
        detail: detail(event.payload.fromDisplayName),
        url: null,
      };
  }
}

function toRow(row: ActivityRow): CanvasTaskActivityRow {
  const at = isoTime(row.ts);
  switch (row.kind) {
    case "task_created":
      return {
        key: row.key,
        kind: row.kind,
        at,
        title: "Task created",
        detail: null,
        url: null,
      };
    case "event":
      return { key: row.key, at, ...eventLine(row) };
    case "human_message":
      return {
        key: row.key,
        kind: row.kind,
        at,
        title: "Message",
        detail: detail(row.message.content),
        url: null,
      };
    case "user_message":
      return {
        key: row.key,
        kind: row.kind,
        at,
        title: "Prompt",
        detail: detail(row.item.content),
        url: null,
      };
    case "comment":
      return {
        key: row.key,
        kind: row.kind,
        at,
        title: row.thread.resolved
          ? "Comment thread, resolved"
          : "Comment thread",
        detail: null,
        url: null,
      };
    case "comment_state":
      return {
        key: row.key,
        kind: row.kind,
        at,
        title:
          row.state === "resolved" ? "Comment resolved" : "Comment reopened",
        detail: null,
        url: null,
      };
    case "run_status":
      return {
        key: row.key,
        kind: row.kind,
        at,
        title: `Run ${row.status}`,
        detail: null,
        url: null,
      };
    case "run_output_pr":
      return {
        key: row.key,
        kind: row.kind,
        at,
        title: "Pull request",
        detail: null,
        url: row.prUrl,
      };
  }
}

export function toCanvasTaskActivity({
  task,
  rows,
  limit = CANVAS_TASK_ACTIVITY_DEFAULT_LIMIT,
}: {
  task: {
    id: string;
    title: string;
    status: string | null;
    createdAt: string;
    updatedAt: string;
  };
  rows: readonly ActivityRow[];
  limit?: number;
}): CanvasTaskActivitySnapshot {
  const bounded = Math.min(
    Math.max(Math.trunc(limit) || CANVAS_TASK_ACTIVITY_DEFAULT_LIMIT, 1),
    CANVAS_TASK_ACTIVITY_MAX_LIMIT,
  );
  // The newest rows are the ones a viewer wants, so an over-long timeline keeps
  // its tail and says so.
  const kept = rows.length > bounded ? rows.slice(rows.length - bounded) : rows;
  return {
    task,
    rows: kept.map(toRow),
    truncated: kept.length < rows.length,
  };
}
