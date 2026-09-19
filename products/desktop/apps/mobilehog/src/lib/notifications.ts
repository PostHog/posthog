import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { Platform } from "react-native";
import { authedFetch, getBaseUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";

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

// Expo issues push tokens only on a physical device with an EAS project id.
async function fetchPushToken(): Promise<string | null> {
  if (!Device.isDevice) return null;
  const projectId = Constants.expoConfig?.extra?.eas?.projectId;
  if (!projectId) return null;
  const { status } = await Notifications.getPermissionsAsync();
  const granted =
    status === "granted" ||
    (await Notifications.requestPermissionsAsync()).status === "granted";
  if (!granted) return null;
  return (await Notifications.getExpoPushTokenAsync({ projectId })).data;
}

let registeredToken: string | null = null;

async function registerPushToken(): Promise<void> {
  const token = await fetchPushToken().catch(() => null);
  if (!token || token === registeredToken) return;
  const response = await authedFetch(
    `${getBaseUrl()}/api/users/@me/push_tokens/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, platform: Platform.OS }),
    },
  );
  if (response.ok) registeredToken = token;
}

export async function unregisterPushToken(): Promise<void> {
  const token = registeredToken;
  registeredToken = null;
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
    if (session) registerPushToken().catch(() => {});
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
