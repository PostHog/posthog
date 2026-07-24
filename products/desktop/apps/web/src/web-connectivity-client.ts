import type { ConnectivityClient } from "@posthog/ui/features/connectivity/connectivityClient";

// Real web connectivity, backed by navigator.onLine and the browser's
// online/offline events. Desktop resolves this over the main-process
// connectivity service (which probes reachability); the browser's own network
// state is the equivalent signal here.
export const webConnectivityClient: ConnectivityClient = {
  getStatus: () => Promise.resolve({ isOnline: navigator.onLine }),
  checkNow: () => Promise.resolve({ isOnline: navigator.onLine }),
  onStatusChange: (sub) => {
    const emit = () => sub.onData({ isOnline: navigator.onLine });
    window.addEventListener("online", emit);
    window.addEventListener("offline", emit);
    return {
      unsubscribe: () => {
        window.removeEventListener("online", emit);
        window.removeEventListener("offline", emit);
      },
    };
  },
};
