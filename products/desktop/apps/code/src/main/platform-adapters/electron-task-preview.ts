import type { WebContents, WebPreferences } from "electron";
import {
  TASK_PREVIEW_ARG,
  TASK_PREVIEW_PARTITION,
} from "../../shared/constants";

const SANDBOX_PREVIEW_HOST_SUFFIX = ".modal.host";
const LOCAL_PREVIEW_HOSTS = new Set(["localhost", "127.0.0.1"]);

export function isAllowedTaskPreviewUrl(
  url: string,
  allowLocalPreviews: boolean,
): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.username || parsed.password) return false;
  if (
    parsed.protocol === "https:" &&
    parsed.hostname.endsWith(SANDBOX_PREVIEW_HOST_SUFFIX)
  ) {
    return true;
  }
  return (
    allowLocalPreviews &&
    parsed.protocol === "http:" &&
    LOCAL_PREVIEW_HOSTS.has(parsed.hostname)
  );
}

export function isAllowedTaskPreview(
  src: string,
  partition: string | undefined,
  allowLocalPreviews: boolean,
): boolean {
  return (
    partition === TASK_PREVIEW_PARTITION &&
    isAllowedTaskPreviewUrl(src, allowLocalPreviews)
  );
}

export function hardenTaskPreviewPreferences(
  preferences: WebPreferences,
  preloadPath: string,
): void {
  preferences.preload = preloadPath;
  preferences.additionalArguments = [TASK_PREVIEW_ARG];
  preferences.nodeIntegration = false;
  preferences.nodeIntegrationInSubFrames = false;
  preferences.contextIsolation = true;
  preferences.sandbox = true;
  preferences.webSecurity = true;
  preferences.allowRunningInsecureContent = false;
  preferences.webviewTag = false;
  preferences.experimentalFeatures = false;
  preferences.enableBlinkFeatures = "";
  preferences.plugins = false;
}

export function lockDownTaskPreview(
  guest: WebContents,
  allowLocalPreviews: boolean,
  openExternal: (url: string) => void,
): void {
  guest.setWindowOpenHandler(({ url }) => {
    openExternal(url);
    return { action: "deny" };
  });
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  guest.on("will-navigate", (event, url) => {
    if (isAllowedTaskPreviewUrl(url, allowLocalPreviews)) return;
    event.preventDefault();
    openExternal(url);
  });

  const guestSession = guest.session;
  guestSession.setPermissionCheckHandler(() => false);
  guestSession.setPermissionRequestHandler((_contents, _permission, callback) =>
    callback(false),
  );
  guestSession.on("will-download", (event) => event.preventDefault());
}
