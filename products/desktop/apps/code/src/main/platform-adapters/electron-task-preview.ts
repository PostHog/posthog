import {
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
  TASK_PREVIEW_TOKEN_PARAM,
} from "../../shared/constants";

const SANDBOX_PREVIEW_HOST_SUFFIX = ".modal.host";
const LOCAL_PREVIEW_HOSTS = new Set(["localhost", "127.0.0.1"]);

function parseUrl(url: string): URL | null {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

export function isAllowedTaskPreviewUrl(url: string): boolean {
  const parsed = parseUrl(url);
  if (!parsed || parsed.username || parsed.password) return false;
  if (parsed.searchParams.has(TASK_PREVIEW_TOKEN_PARAM)) return false;
  if (
    parsed.protocol === "https:" &&
    parsed.hostname.endsWith(SANDBOX_PREVIEW_HOST_SUFFIX)
  ) {
    return true;
  }
  return (
    parsed.protocol === "http:" && LOCAL_PREVIEW_HOSTS.has(parsed.hostname)
  );
}

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

function isPrivateNetworkHost(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (host === "::1" || host === "::" || host.startsWith("fe80:")) return true;
  if (host.startsWith("fc") || host.startsWith("fd")) return host.includes(":");
  const octets = host.split(".").map(Number);
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part))) {
    return false;
  }
  const [a, b] = octets;
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127)
  );
}

export function isBlockedPreviewRequest(
  pageUrl: string,
  requestUrl: string,
): boolean {
  const request = parseUrl(requestUrl);
  if (!request) return true;
  if (
    !["http:", "https:", "ws:", "wss:", "data:", "blob:"].includes(
      request.protocol,
    )
  ) {
    return true;
  }
  const page = parseUrl(pageUrl);
  if (!page || page.protocol !== "https:") return false;
  return isPrivateNetworkHost(request.hostname);
}

const lockedSessions = new WeakSet<Session>();

export function lockDownTaskPreview(
  guest: WebContents,
  openExternal: (url: string) => void,
): void {
  guest.setWindowOpenHandler(({ url }) => {
    openExternal(url);
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

  const guestSession = guest.session;
  if (lockedSessions.has(guestSession)) return;
  lockedSessions.add(guestSession);
  guestSession.setPermissionCheckHandler(() => false);
  guestSession.setPermissionRequestHandler((_contents, _permission, callback) =>
    callback(false),
  );
  guestSession.on("will-download", (event) => event.preventDefault());
  guestSession.webRequest.onBeforeRequest((details, callback) => {
    const page =
      details.webContentsId === undefined
        ? undefined
        : webContents.fromId(details.webContentsId);
    const pageUrl = page?.getURL() || details.url;
    callback({ cancel: isBlockedPreviewRequest(pageUrl, details.url) });
  });
}
