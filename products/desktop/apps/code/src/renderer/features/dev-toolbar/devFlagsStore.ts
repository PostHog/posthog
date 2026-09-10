import { trpcClient } from "@renderer/trpc/client";
import { logger } from "@utils/logger";
import { create } from "zustand";
import { BOOT_DEV_FLAGS } from "./devModeBoot";
import { setReactGrabEnabled } from "./reactGrab";
import { setReactScanEnabled } from "./reactScan";

const log = logger.scope("dev-flags-store");

interface DevFlagsState {
  devMode: boolean;
  reactGrabEnabled: boolean;
  reactScanEnabled: boolean;
  setDevMode: (enabled: boolean) => Promise<void>;
  setReactGrabEnabled: (enabled: boolean) => void;
  setReactScanEnabled: (enabled: boolean) => void;
}

export const useDevFlagsStore = create<DevFlagsState>()((set) => ({
  devMode: BOOT_DEV_FLAGS.devMode,
  reactGrabEnabled: false,
  reactScanEnabled: false,

  setDevMode: async (enabled) => {
    try {
      const updated = await trpcClient.dev.setDevMode.mutate({ enabled });
      set({ devMode: updated.devMode });
    } catch (error) {
      log.warn("Failed to set dev mode", { error });
    }
  },

  setReactGrabEnabled: (enabled) => {
    set({ reactGrabEnabled: enabled });
    void setReactGrabEnabled(enabled);
  },

  setReactScanEnabled: (enabled) => {
    set({ reactScanEnabled: enabled });
    void setReactScanEnabled(enabled);
  },
}));

export function subscribeDevFlagsFromMain(): () => void {
  const subscription = trpcClient.dev.onFlagsChanged.subscribe(undefined, {
    onData: (flags) => {
      useDevFlagsStore.setState({ devMode: flags.devMode });
    },
    onError: (error) => {
      log.warn("Dev flags subscription error", { error });
    },
  });
  return () => subscription.unsubscribe();
}
