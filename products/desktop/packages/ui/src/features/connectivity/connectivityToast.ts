import { connectivityStore } from "@posthog/core/connectivity/connectivityStore";
import { toast } from "../../primitives/toast";

// The live offline toast's id, tracked so re-entry never stacks a second one and
// reconnect dismisses exactly this toast.
let offlineToastId: string | undefined;

/**
 * Surfaces the offline toast for an action the user just tried and that the
 * network blocked. Going offline on its own does not raise a toast — the shell's
 * ConnectivityBanner already reports that state.
 */
export function showOfflineToast() {
  if (offlineToastId) return;
  offlineToastId = toast.error("No internet connection", {
    duration: Number.POSITIVE_INFINITY,
    description:
      "PostHog features that need the network are paused until you reconnect.",
  });
}

function dismissOfflineToast() {
  if (!offlineToastId) return;
  toast.dismiss(offlineToastId);
  offlineToastId = undefined;
}

// The action toast has no duration, so it needs the reconnect to clear it.
export function initializeConnectivityToastDismissal() {
  let wasOnline = connectivityStore.getState().isOnline;

  return connectivityStore.subscribe((state) => {
    if (state.isOnline === wasOnline) return;
    wasOnline = state.isOnline;

    if (state.isOnline) {
      dismissOfflineToast();
    }
  });
}
