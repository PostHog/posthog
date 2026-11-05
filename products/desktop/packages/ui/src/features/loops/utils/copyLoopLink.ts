import { ANALYTICS_EVENTS, buildLoopDeeplink } from "@posthog/shared";
import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";

/**
 * Copy a deep link (`<scheme>://loop/{loopId}`) for a loop to the clipboard,
 * toasting success or failure. The inbound side lives in `useLoopDeepLink`.
 */
export function copyLoopLink(loop: Pick<LoopSchemas.Loop, "id">): void {
  const url = buildLoopDeeplink(loop.id, {
    isDevBuild: import.meta.env.DEV,
  });
  navigator.clipboard
    .writeText(url)
    .then(() => {
      toast.success("Link copied");
      track(ANALYTICS_EVENTS.LOOP_LINK_COPIED, { loop_id: loop.id });
    })
    .catch(() => toast.error("Couldn't copy link"));
}
