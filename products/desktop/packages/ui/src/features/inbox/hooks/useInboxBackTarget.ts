import { useLocation } from "@tanstack/react-router";

const INBOX_LIST_ROUTE_VALUES = [
  "/inbox/pulls",
  "/inbox/reports",
  "/inbox/runs",
  "/inbox/dismissed",
] as const;

/** List routes an inbox detail screen's back link can return to. */
export type InboxListRoute = (typeof INBOX_LIST_ROUTE_VALUES)[number];

/**
 * Where a detail screen's back link should go. The Archive redirect records the
 * origin here so a report archived while open keeps "Back to reports" (or pulls
 * / runs) instead of flipping to "Back to archive" the moment its status
 * changes. The back link follows the path the user took in, not the report's
 * current state.
 */
export interface InboxBackTarget {
  to: InboxListRoute;
  label: string;
}

export interface InboxTriageOrigin {
  reportId: string;
}

// Carried in history state across the status↔route redirect; declared here so
// `navigate({ state })` and `useLocation().state` stay typed.
declare module "@tanstack/react-router" {
  interface HistoryState {
    inboxBackOrigin?: InboxBackTarget;
    inboxTriageOrigin?: InboxTriageOrigin;
  }
}

const INBOX_LIST_ROUTES = new Set<InboxListRoute>(INBOX_LIST_ROUTE_VALUES);

/**
 * Validate untyped history state before trusting it: it may have come from an
 * older app version, a hand-edited URL, or a corrupted entry.
 */
export function asInboxBackTarget(value: unknown): InboxBackTarget | null {
  if (!value || typeof value !== "object") return null;
  const { to, label } = value as Record<string, unknown>;
  if (typeof label !== "string" || label.length === 0) return null;
  if (typeof to !== "string" || !INBOX_LIST_ROUTES.has(to as InboxListRoute)) {
    return null;
  }
  return { to: to as InboxListRoute, label };
}

export function asInboxTriageOrigin(value: unknown): InboxTriageOrigin | null {
  if (!value || typeof value !== "object") return null;
  const { reportId } = value as Record<string, unknown>;
  return typeof reportId === "string" && reportId.length > 0
    ? { reportId }
    : null;
}

export function useInboxTriageOrigin(): InboxTriageOrigin | null {
  const origin = useLocation({
    select: (location) => location.state.inboxTriageOrigin,
  });
  return asInboxTriageOrigin(origin);
}

/**
 * Resolves a detail screen's back link: the origin recorded when the status↔route
 * redirect carried us here, or `fallback` when we arrived directly (deep link,
 * tab click, or a page refresh that dropped the history state).
 */
export function useInboxBackTarget(fallback: InboxBackTarget): InboxBackTarget {
  const origin = useLocation({
    select: (location) => location.state.inboxBackOrigin,
  });
  return asInboxBackTarget(origin) ?? fallback;
}
