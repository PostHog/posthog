import type { DesktopAccess } from "@posthog/core/auth/schemas";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect } from "react";

export function useDesktopAccessAnalytics(
  access: DesktopAccess,
  hasOtherOrganizations: boolean,
  unchangedRechecks: number,
): void {
  const reason =
    access.status === "blocked" ? (access.reason ?? "unknown") : null;

  useEffect(() => {
    if (!reason) return;
    track(ANALYTICS_EVENTS.DESKTOP_ACCESS_BLOCKED, {
      reason,
      has_other_organizations: hasOtherOrganizations,
    });
  }, [reason, hasOtherOrganizations]);

  useEffect(() => {
    if (!reason || unchangedRechecks === 0) return;
    track(ANALYTICS_EVENTS.DESKTOP_ACCESS_RECHECKED, {
      reason,
      has_other_organizations: hasOtherOrganizations,
      attempt: unchangedRechecks,
    });
  }, [reason, hasOtherOrganizations, unchangedRechecks]);
}
