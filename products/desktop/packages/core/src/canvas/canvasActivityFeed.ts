/**
 * The JSON view of a person's activity feed that a canvas reads through
 * `ph.activityFeed()`.
 *
 * The Activity page renders its own rows from `TaskActivityItem` and
 * `SignalReport`, but a canvas runs in a sandboxed iframe: it can only receive
 * structured-clone data, and it must not depend on those types, whose shape
 * follows the built page. So the host flattens every entry to a printable line
 * here, and this file is the contract a canvas author writes against.
 */

import type { TaskActivityItem } from "./taskActivity";

export type CanvasActivityRowKind = "task" | "canvas" | "report";

export interface CanvasActivityRow {
  /** Stable across polls, so a canvas can key its list on it. */
  key: string;
  kind: CanvasActivityRowKind;
  /** ISO 8601, UTC. */
  at: string;
  /** One line, ready to print: the task title, the canvas name, the report title. */
  title: string;
  /** The latest message, the report summary, or null. */
  detail: string | null;
  /** The space the row belongs to, when it has one. */
  space: string | null;
  /** True for a task update the viewer has not read. Always false elsewhere. */
  unread: boolean;
  /** The id to hand to `ph.navigate.toTask` or `ph.navigate.toCanvas`. Null on
   *  a report, which a canvas cannot open. */
  targetId: string | null;
}

export interface CanvasActivityFeedSnapshot {
  /** Newest first, the order the Activity page reads in. */
  rows: CanvasActivityRow[];
  /** Unread task updates, including any the row limit dropped. */
  unreadCount: number;
  /** True when older rows were dropped to hold the row limit. */
  truncated: boolean;
}

/** A canvas the viewer worked on, as the feed needs it. */
export interface FeedCanvasLike {
  id: string;
  name: string;
  /** Epoch milliseconds. */
  updatedAt: number;
  spaceName: string | null;
}

/** A self-driving report, as the feed needs it. */
export interface FeedReportLike {
  id: string;
  title: string;
  summary: string | null;
  createdAt: string;
}

export const CANVAS_ACTIVITY_FEED_DEFAULT_LIMIT = 100;
export const CANVAS_ACTIVITY_FEED_MAX_LIMIT = 500;
/** A message can be very long, and the whole feed crosses the bridge on every
 *  poll, so each line carries a preview instead of the full text. */
const MAX_DETAIL_LENGTH = 500;

function detail(value: string | null | undefined): string | null {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return null;
  return trimmed.length > MAX_DETAIL_LENGTH
    ? `${trimmed.slice(0, MAX_DETAIL_LENGTH)}…`
    : trimmed;
}

function isoTime(value: string | number): string {
  const parsed = typeof value === "number" ? value : Date.parse(value);
  return Number.isFinite(parsed) && parsed > 0
    ? new Date(parsed).toISOString()
    : new Date(0).toISOString();
}

function taskRow(item: TaskActivityItem): CanvasActivityRow {
  return {
    key: `task:${item.id}`,
    kind: "task",
    at: isoTime(item.activityAt),
    title: item.taskTitle,
    detail: detail(item.snippet),
    space: item.channelName,
    unread: item.isUnread,
    targetId: item.taskId,
  };
}

function canvasRow(canvas: FeedCanvasLike): CanvasActivityRow {
  return {
    key: `canvas:${canvas.id}`,
    kind: "canvas",
    at: isoTime(canvas.updatedAt),
    title: canvas.name,
    detail: null,
    space: canvas.spaceName,
    unread: false,
    targetId: canvas.id,
  };
}

function reportRow(report: FeedReportLike): CanvasActivityRow {
  return {
    key: `report:${report.id}`,
    kind: "report",
    at: isoTime(report.createdAt),
    title: report.title,
    detail: detail(report.summary),
    space: null,
    unread: false,
    targetId: null,
  };
}

export function toCanvasActivityFeed({
  taskItems,
  canvases,
  reports,
  limit = CANVAS_ACTIVITY_FEED_DEFAULT_LIMIT,
}: {
  taskItems: readonly TaskActivityItem[];
  canvases: readonly FeedCanvasLike[];
  reports: readonly FeedReportLike[];
  limit?: number;
}): CanvasActivityFeedSnapshot {
  const bounded = Math.min(
    Math.max(Math.trunc(limit) || CANVAS_ACTIVITY_FEED_DEFAULT_LIMIT, 1),
    CANVAS_ACTIVITY_FEED_MAX_LIMIT,
  );
  const rows = [
    ...taskItems.map(taskRow),
    ...canvases.map(canvasRow),
    ...reports.map(reportRow),
  ].sort((left, right) => right.at.localeCompare(left.at));

  return {
    rows: rows.slice(0, bounded),
    // Counted over every task row, not over the ones that survived the limit:
    // this is the same number the rail's Activity badge shows.
    unreadCount: taskItems.filter((item) => item.isUnread).length,
    truncated: rows.length > bounded,
  };
}
