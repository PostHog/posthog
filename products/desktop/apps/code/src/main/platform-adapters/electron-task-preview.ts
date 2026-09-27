import {
  createNewWindowLimiter,
  isAllowedTaskPreviewUrl,
  isBlockedPreviewRequest,
  parseUrl,
  protectedLoopbackPorts,
} from "@posthog/core/task-browser/guest-policy";
import { TASK_PREVIEW_TOKEN_PARAM } from "@posthog/shared/constants";
import {
  app,
  type Cookies,
  type Session,
  session,
  type WebContents,
  type WebPreferences,
  webContents,
} from "electron";
import {
  TASK_PREVIEW_ARG,
  TASK_PREVIEW_PARTITION,
} from "../../shared/constants";

export function isAllowedTaskPreview(
  src: string,
  partition: string | undefined,
): boolean {
  return partition === TASK_PREVIEW_PARTITION && isAllowedTaskPreviewUrl(src);
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

export async function authorizeTaskPreview(
  target: string,
  cookies: Pick<Cookies, "set">,
): Promise<string | null> {
  const url = parseUrl(target);
  if (!url) return null;
  const token = url.searchParams.get(TASK_PREVIEW_TOKEN_PARAM);
  url.searchParams.delete(TASK_PREVIEW_TOKEN_PARAM);
  const bare = url.toString();
  if (!isAllowedTaskPreviewUrl(bare)) return null;
  if (!token) return url.protocol === "http:" ? bare : null;
  if (url.protocol !== "https:") return null;
  await cookies.set({
    url: url.origin,
    name: TASK_PREVIEW_TOKEN_PARAM,
    value: token,
    path: "/",
    secure: true,
    httpOnly: true,
    sameSite: "strict",
  });
  return bare;
}

export function authorizePartitionPreview(
  target: string,
): Promise<string | null> {
  return authorizeTaskPreview(
    target,
    session.fromPartition(TASK_PREVIEW_PARTITION).cookies,
  );
}

const lockedSessions = new WeakSet<Session>();

export function lockDownTaskPreview(
  guest: WebContents,
  openExternal: (url: string) => void,
): void {
  const mayOpen = createNewWindowLimiter();
  guest.setWindowOpenHandler(({ url }) => {
    if (mayOpen()) openExternal(url);
    return { action: "deny" };
  });
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  let pinnedOrigin: string | null = null;
  const sameOrigin = (url: string) => parseUrl(url)?.origin === pinnedOrigin;
  guest.on("did-start-navigation", (event) => {
    if (pinnedOrigin || !event.isMainFrame) return;
    if (isAllowedTaskPreviewUrl(event.url)) {
      pinnedOrigin = parseUrl(event.url)?.origin ?? null;
    }
  });
  guest.on("will-navigate", (event, url) => {
    if (sameOrigin(url)) return;
    event.preventDefault();
    openExternal(url);
  });
  guest.on("will-redirect", (event, url) => {
    if (event.isMainFrame && pinnedOrigin && !sameOrigin(url)) {
      event.preventDefault();
    }
  });

  lockDownGuestSession(guest.session);
}

export function lockDownGuestSession(guestSession: Session): void {
  if (lockedSessions.has(guestSession)) return;
  lockedSessions.add(guestSession);
  guestSession.setPermissionCheckHandler(() => false);
  guestSession.setPermissionRequestHandler((_contents, _permission, callback) =>
    callback(false),
  );
  guestSession.on("will-download", (event) => event.preventDefault());
  const protectedPorts = protectedLoopbackPorts(
    app.commandLine.getSwitchValue("remote-debugging-port") || undefined,
    process.env.ELECTRON_RENDERER_URL,
  );
  guestSession.webRequest.onBeforeRequest((details, callback) => {
    const pageUrl =
      details.resourceType === "mainFrame"
        ? details.url
        : (details.webContentsId === undefined
            ? undefined
            : webContents.fromId(details.webContentsId)?.getURL()) ||
          "about:blank";
    callback({
      cancel: isBlockedPreviewRequest(pageUrl, details.url, protectedPorts),
    });
  });
}
