import { trpcClient } from "@renderer/trpc/client";
import { logger } from "@utils/logger";
import { create } from "zustand";
import { BOOT_DEV_FLAGS } from "./devModeBoot";
import { setReactScanEnabled } from "./reactScan";

const log = logger.scope("dev-flags-store");

interface DevFlagsState {
  devMode: boolean;
  reactScanEnabled: boolean;
  setDevMode: (enabled: boolean) => Promise<void>;
  setReactScanEnabled: (enabled: boolean) => void;
}

export const useDevFlagsStore = create<DevFlagsState>()((set) => ({
  devMode: BOOT_DEV_FLAGS.devMode,
  reactScanEnabled: false,

  setDevMode: async (enabled) => {
    try {
      const updated = await trpcClient.dev.setDevMode.mutate({ enabled });
      set({ devMode: updated.devMode });
    } catch (error) {
      log.warn("Failed to set dev mode", { error });
    }
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
