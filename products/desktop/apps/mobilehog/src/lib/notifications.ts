import Constants from "expo-constants";
import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { AppState, Platform } from "react-native";
import { create } from "zustand";
import { authedFetch, getBaseUrl } from "@/lib/api";
import { sessionIdentity, useAuth } from "@/lib/auth";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

// The server sends `{ url: "posthog://task/<id>" }` or a legacy `{ taskId }`.
function pathFromNotification(
  notification: Notifications.Notification,
): string | null {
  const data = notification.request.content.data as Record<string, unknown>;
  if (typeof data.url === "string") {
    return data.url.replace(/^[a-z]+:\/\//, "/").replace(/^\/\/+/, "/");
  }
  if (typeof data.taskId === "string") return `/task/${data.taskId}`;
  return null;
}

type PushStatus =
  | "checking"
  | "ready"
  | "permissionDenied"
  | "unavailable"
  | "failed";

export const usePushStatus = create<{ status: PushStatus }>(() => ({
  status: "checking",
}));

async function fetchPushToken(): Promise<{
  token: string | null;
  status?: PushStatus;
}> {
  const projectId =
    Constants.easConfig?.projectId ??
    Constants.expoConfig?.extra?.eas?.projectId;
  if (Platform.OS === "web" || !projectId) {
    return { token: null, status: "unavailable" };
  }
  const { status } = await Notifications.getPermissionsAsync();
  const granted =
    status === "granted" ||
    (await Notifications.requestPermissionsAsync()).status === "granted";
  if (!granted) {
    return { token: null, status: "permissionDenied" };
  }
  return {
    token: (await Notifications.getExpoPushTokenAsync({ projectId })).data,
  };
}

let registeredToken: string | null = null;
let pendingRegistration: { identity: string; promise: Promise<void> } | null =
  null;

export function registerPushToken(): Promise<void> {
  if (!useAuth.getState().session) return Promise.resolve();
  const identity = sessionIdentity();
  if (pendingRegistration?.identity === identity)
    return pendingRegistration.promise;
  usePushStatus.setState({ status: "checking" });
  const promise = (async () => {
    try {
      const { token, status } = await fetchPushToken();
      if (sessionIdentity() !== identity) return;
      if (!token) {
        usePushStatus.setState({ status: status ?? "failed" });
        return;
      }
      const response = await authedFetch(
        `${getBaseUrl()}/api/users/@me/push_tokens/`,
        {
          method: "POST",
          body: JSON.stringify({ token, platform: Platform.OS }),
        },
      );
      if (sessionIdentity() !== identity) return;
      if (!response.ok) {
        usePushStatus.setState({ status: "failed" });
        return;
      }
      registeredToken = token;
      usePushStatus.setState({ status: "ready" });
    } catch {
      if (sessionIdentity() === identity)
        usePushStatus.setState({ status: "failed" });
    }
  })().finally(() => {
    if (pendingRegistration?.promise === promise) pendingRegistration = null;
  });
  pendingRegistration = { identity, promise };
  return promise;
}

export async function unregisterPushToken(): Promise<void> {
  await pendingRegistration?.promise;
  const token = registeredToken;
  registeredToken = null;
  usePushStatus.setState({ status: "checking" });
  if (!token) return;
  await authedFetch(`${getBaseUrl()}/api/users/@me/push_tokens/unregister/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  }).catch(() => {});
}

// Registers the device once a session exists and routes notification taps.
export function usePushNotifications(): void {
  const session = useAuth((s) => s.session);
  const router = useRouter();

  useEffect(() => {
    if (!session) return;
    void registerPushToken();
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void registerPushToken();
    });
    return () => subscription.remove();
  }, [session]);

  useEffect(() => {
    const open = (response: Notifications.NotificationResponse): void => {
      const path = pathFromNotification(response.notification);
      if (path) router.push(path as never);
    };
    Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) open(response);
    });
    const sub = Notifications.addNotificationResponseReceivedListener(open);
    return () => sub.remove();
  }, [router]);
}
