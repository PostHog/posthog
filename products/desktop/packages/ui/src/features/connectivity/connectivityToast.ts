import { connectivityStore } from "@posthog/core/connectivity/connectivityStore";
import { toast } from "../../primitives/toast";

const OFFLINE_DEBOUNCE_MS = 5_000;

// The live offline toast's id, tracked so re-entry never stacks a second one and
// reconnect dismisses exactly this toast.
let offlineToastId: string | undefined;

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

// Debounces flaky transitions: only surfaces a toast when continuously offline
// for OFFLINE_DEBOUNCE_MS. A single tracked toast id guarantees it never stacks.
export function initializeConnectivityToast() {
  let pendingTimer: ReturnType<typeof setTimeout> | null = null;
  let wasOnline = connectivityStore.getState().isOnline;

  const clearPending = () => {
    if (pendingTimer) {
      clearTimeout(pendingTimer);
      pendingTimer = null;
    }
  };

  const unsubscribe = connectivityStore.subscribe((state) => {
    if (state.isOnline === wasOnline) return;
    wasOnline = state.isOnline;

    if (!state.isOnline) {
      clearPending();
      pendingTimer = setTimeout(() => {
        pendingTimer = null;
        showOfflineToast();
      }, OFFLINE_DEBOUNCE_MS);
    } else {
      clearPending();
      dismissOfflineToast();
    }
  });

  return () => {
    clearPending();
    unsubscribe();
  };
}
