import { createContext, useContext } from "react";

/**
 * Whether the open report's status is the server's answer rather than a cache
 * snapshot. False only while a detail screen's post-mount fetch is in flight on
 * a per-status route, where the cached status can already be stale: another
 * session may have archived the report, and the route redirect that follows
 * acts on the confirmed status.
 *
 * Read by the triage actions so they hold off for that one round trip while the
 * report body stays on screen. Defaults to confirmed, so the same actions work
 * unchanged on surfaces outside a detail screen.
 */
export const InboxReportStatusConfirmedContext = createContext(true);

export function useInboxReportStatusConfirmed(): boolean {
  return useContext(InboxReportStatusConfirmedContext);
}
