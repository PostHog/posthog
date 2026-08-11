import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { create } from "zustand";
import { deletePushToken, registerPushToken } from "@/lib/api";
import { logger } from "@/lib/logger";
import { registerForPushNotificationsAsync } from "../lib/notifications";

const log = logger.scope("push-token-store");

const TOKEN_KEY = "posthog_expo_push_token";
const LAST_UPLOADED_KEY = "posthog_expo_push_token_uploaded";

interface PushTokenState {
  expoPushToken: string | null;
  lastUploadedToken: string | null;
  isHydrated: boolean;

  hydrate: () => Promise<void>;
  registerAndUpload: () => Promise<void>;
  clear: () => Promise<void>;
}

async function readSecure(key: string): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(key);
  } catch (err) {
    log.warn("SecureStore read failed", { key, error: err });
    return null;
  }
}

async function writeSecure(key: string, value: string | null): Promise<void> {
  try {
    if (value === null) {
      await SecureStore.deleteItemAsync(key);
    } else {
      await SecureStore.setItemAsync(key, value);
    }
  } catch (err) {
    log.warn("SecureStore write failed", { key, error: err });
  }
}

export const usePushTokenStore = create<PushTokenState>((set, get) => ({
  expoPushToken: null,
  lastUploadedToken: null,
  isHydrated: false,

  hydrate: async () => {
    if (get().isHydrated) return;
    const [expoPushToken, lastUploadedToken] = await Promise.all([
      readSecure(TOKEN_KEY),
      readSecure(LAST_UPLOADED_KEY),
    ]);
    set({ expoPushToken, lastUploadedToken, isHydrated: true });
  },

  registerAndUpload: async () => {
    await get().hydrate();

    const token = await registerForPushNotificationsAsync();
    if (!token) return;

    if (token !== get().expoPushToken) {
      await writeSecure(TOKEN_KEY, token);
      set({ expoPushToken: token });
    }

    if (token === get().lastUploadedToken) return;

    try {
      await registerPushToken({ token, platform: Platform.OS });
      await writeSecure(LAST_UPLOADED_KEY, token);
      set({ lastUploadedToken: token });
    } catch (err) {
      // Surface as warn so a misconfigured OAuth scope or backend regression
      // doesn't fail silently — push notifications won't work until this row
      // lands on the backend.
      log.warn("Push token upload failed", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  },

  clear: async () => {
    const { expoPushToken } = get();
    if (expoPushToken) {
      try {
        await deletePushToken({ token: expoPushToken });
      } catch (err) {
        log.debug("Push token delete failed", { error: err });
      }
    }
    await Promise.all([
      writeSecure(TOKEN_KEY, null),
      writeSecure(LAST_UPLOADED_KEY, null),
    ]);
    set({ expoPushToken: null, lastUploadedToken: null });
  },
}));
