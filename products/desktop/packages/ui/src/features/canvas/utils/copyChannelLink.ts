import {
  ANALYTICS_EVENTS,
  type ChannelsSurface,
} from "@posthog/shared/analytics-events";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { channelShareUrl } from "@posthog/ui/utils/posthogLinks";

/**
 * Copy a channel's — or, with `taskId`, a thread's — shareable https link
 * (`<instance>/code/channel/<channelId>[/tasks/<taskId>]`) to the clipboard,
 * toasting success or failure. Mirrors `copyCanvasLink`: the https link
 * resolves to a web interstitial that deep-links into the desktop app, so it
 * opens for anyone whether or not they have the app installed.
 */
export async function copyChannelLink(
  channelId: string,
  surface: ChannelsSurface,
  taskId?: string,
): Promise<void> {
  const url = channelShareUrl(channelId, taskId);
  if (!url) {
    toast.error("Couldn't build a shareable link");
    return;
  }

  const target = taskId ? "thread" : "channel";
  try {
    await navigator.clipboard.writeText(url);
    toast.success("Link copied", {
      description: `Anyone with the link can open this ${target}.`,
    });
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "copy_link",
      surface,
      channel_id: channelId,
      task_id: taskId,
      success: true,
    });
  } catch (error) {
    toast.error("Couldn't copy link", {
      description: error instanceof Error ? error.message : String(error),
    });
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "copy_link",
      surface,
      channel_id: channelId,
      task_id: taskId,
      success: false,
    });
  }
}
