import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";

// Where a canvas create was triggered from, for analytics.
export type CreateSurface = "dashboards_grid" | "sidebar" | "channel_home";

// Fire the "create" DASHBOARD_ACTION, then create + open the canvas. Shared so
// every canvas-create entry point (the dashboards-grid dialog, the sidebar "+"
// dropdown, the channel composer's canvas mode) reports creation the same way.
// Returns `create`'s result so callers that need the created record can await
// it.
export function trackAndCreateCanvas<T>(
  channelId: string | undefined,
  templateId: string | undefined,
  surface: CreateSurface,
  create: () => T,
): T {
  track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
    action_type: "create",
    surface,
    channel_id: channelId,
    template_id: templateId,
  });
  return create();
}
