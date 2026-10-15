import { onlineManager } from "@tanstack/react-query";
import * as Network from "expo-network";
import { create } from "zustand";
import { useSessions } from "@/lib/session";

export const useOnline = create<{ online: boolean }>(() => ({ online: true }));

// Queries pause instead of failing while offline, and live chats reconnect after.
onlineManager.setEventListener((setOnline) => {
  const update = (state: Network.NetworkState): void => {
    const online =
      state.isConnected !== false && state.isInternetReachable !== false;
    if (online && !useOnline.getState().online) {
      useSessions.getState().reconnect();
    }
    useOnline.setState({ online });
    setOnline(online);
  };
  Network.getNetworkStateAsync()
    .then(update)
    .catch(() => {});
  const subscription = Network.addNetworkStateListener(update);
  return () => subscription.remove();
});
