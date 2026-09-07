import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";

// Where a canvas create was triggered from, for analytics.
export type CreateSurface = "dashboards_grid";

// Fire the "create" DASHBOARD_ACTION, then create and open the canvas.
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
