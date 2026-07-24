import {
  ANALYTICS_EVENTS,
  type ChannelsSurface,
} from "@posthog/shared/analytics-events";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { canvasShareUrl } from "@posthog/ui/utils/posthogLinks";

/**
 * Copy a canvas's shareable https link (`<instance>/code/canvas/<channelId>/
 * <dashboardId>`) to the clipboard, toasting success or failure. Shared by every
 * "Copy link" affordance (canvas toolbar, dashboards grid) so the link format
 * and feedback stay in one place. Unlike the inbox/scout copy actions — which
 * copy the raw `<scheme>://` deep link — this copies an https link that resolves
 * to a web interstitial, so it opens for anyone whether or not they have the
 * desktop app.
 */
export async function copyCanvasLink(
  channelId: string,
  dashboardId: string,
  surface: ChannelsSurface,
): Promise<void> {
  const url = canvasShareUrl(channelId, dashboardId);
  if (!url) {
    toast.error("Couldn't build a shareable link");
    return;
  }

  try {
    await navigator.clipboard.writeText(url);
    toast.success("Link copied", {
      description: "Anyone with the link can open this canvas.",
    });
    track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
      action_type: "link_copied",
      surface,
      channel_id: channelId,
      dashboard_id: dashboardId,
      success: true,
    });
  } catch (error) {
    toast.error("Couldn't copy link", {
      description: error instanceof Error ? error.message : String(error),
    });
    track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
      action_type: "link_copied",
      surface,
      channel_id: channelId,
      dashboard_id: dashboardId,
      success: false,
    });
  }
}
