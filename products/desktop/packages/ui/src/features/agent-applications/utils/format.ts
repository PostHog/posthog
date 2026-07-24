import type {
  AgentApprovalRequestState,
  AgentRevisionState,
  AgentSessionState,
  AgentUserWithConnections,
} from "@posthog/shared/agent-platform-types";

/**
 * Display name from a user's trigger-stamped metadata (`display_name` → `name`),
 * or null when neither is present. Shared by the Users pane and the Sessions
 * user-filter so the resolution lives in one place.
 */
export function userDisplayName(user: AgentUserWithConnections): string | null {
  const meta = user.metadata;
  if (typeof meta?.display_name === "string") return meta.display_name;
  if (typeof meta?.name === "string") return meta.name;
  return null;
}
/** Formats a USD spend value for the fleet / agent stat strips. */
export function formatSpendUsd(value: number | null | undefined): string {
  if (value == null) return "$0";
  // Clamp non-positive to $0: cost is never legitimately negative, and an
  // upstream cost-calc artifact (negative `$ai_total_cost_usd`) shouldn't
  // surface as "-$2.74" or fall into the sub-cent "<$0.01" branch below.
  if (value <= 0) return "$0";
  if (value < 0.01) return "<$0.01";
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Radix Badge colour for a session lifecycle state. */
export function sessionStateColor(
  state: AgentSessionState,
): "green" | "blue" | "gray" | "red" | "amber" {
  switch (state) {
    case "running":
      return "blue";
    case "queued":
      return "amber";
    case "completed":
    case "closed":
      return "green";
    case "failed":
      return "red";
    case "cancelled":
      return "gray";
    default:
      return "gray";
  }
}

/** Radix Badge colour for a tool-approval request state. */
export function approvalStateColor(
  state: AgentApprovalRequestState,
): "green" | "blue" | "gray" | "red" | "amber" {
  switch (state) {
    case "queued":
      return "amber";
    case "approving":
      return "blue";
    case "dispatched":
      return "green";
    case "dispatched_failed":
    case "rejected":
      return "red";
    default:
      return "gray";
  }
}

/** Human label for a tool-approval request state. */
export function approvalStateLabel(state: AgentApprovalRequestState): string {
  switch (state) {
    case "dispatched":
      return "approved";
    case "dispatched_failed":
      return "dispatch failed";
    default:
      return state;
  }
}

/** Dot/text colour CSS var for a log level. */
export function logLevelColor(level: string): string {
  switch (level.toUpperCase()) {
    case "ERROR":
    case "FATAL":
      return "var(--red-9)";
    case "WARN":
    case "WARNING":
      return "var(--amber-9)";
    case "INFO":
      return "var(--blue-9)";
    case "DEBUG":
      return "var(--gray-7)";
    default:
      return "var(--gray-9)";
  }
}

/** Compact elapsed time between two ISO timestamps (e.g. "1.2s", "3m 4s"). */
export function formatDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const s = ms / 1000;
  if (s < 1) return `${Math.round(ms)}ms`;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m ${rem}s`;
}

/** Radix Badge colour for a revision lifecycle state. */
export function revisionStateColor(
  state: AgentRevisionState,
): "green" | "blue" | "gray" | "amber" {
  switch (state) {
    case "live":
      return "green";
    case "ready":
      return "blue";
    case "draft":
      return "amber";
    default:
      return "gray";
  }
}
